import time
import sys

from unitree_sdk2py.core.channel import ChannelPublisher, ChannelFactoryInitialize
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowState_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
from unitree_sdk2py.utils.crc import CRC
from unitree_sdk2py.utils.thread import RecurrentThread
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

import numpy as np

kPi = 3.141592654
kPi_2 = 1.57079632      # 半圆

class G1JointIndex:
    # Left leg
    LeftHipPitch = 0
    LeftHipRoll = 1
    LeftHipYaw = 2
    LeftKnee = 3
    LeftAnklePitch = 4
    LeftAnkleB = 4
    LeftAnkleRoll = 5
    LeftAnkleA = 5

    # Right leg
    RightHipPitch = 6
    RightHipRoll = 7
    RightHipYaw = 8
    RightKnee = 9
    RightAnklePitch = 10
    RightAnkleB = 10
    RightAnkleRoll = 11
    RightAnkleA = 11

    WaistYaw = 12
    WaistRoll = 13        # NOTE: INVALID for g1 23dof/29dof with waist locked
    WaistA = 13           # NOTE: INVALID for g1 23dof/29dof with waist locked
    WaistPitch = 14       # NOTE: INVALID for g1 23dof/29dof with waist locked
    WaistB = 14           # NOTE: INVALID for g1 23dof/29dof with waist locked

    # Left arm
    LeftShoulderPitch = 15
    LeftShoulderRoll = 16
    LeftShoulderYaw = 17
    LeftElbow = 18
    LeftWristRoll = 19
    LeftWristPitch = 20   # NOTE: INVALID for g1 23dof
    LeftWristYaw = 21     # NOTE: INVALID for g1 23dof

    # Right arm
    RightShoulderPitch = 22
    RightShoulderRoll = 23
    RightShoulderYaw = 24
    RightElbow = 25
    RightWristRoll = 26
    RightWristPitch = 27  # NOTE: INVALID for g1 23dof
    RightWristYaw = 28    # NOTE: INVALID for g1 23dof

    kNotUsedJoint = 29      # NOTE: Weight

class Custom:
    # 初始化控制参数和动作数据
    def __init__(self):
        self.time_ = 0.0
        self.control_dt_ = 0.02     # 控制频率，表示每0.02s发一次命令，约50Hz，可以根据需要调整，调快可以让动作更流畅，但对通信和控制性能要求更高，建议先调慢测试。初始是20ms发一次命令。
        self.duration_ = 2.0        # 运动速度，建议先调慢，初始是3秒完成一个动作
        self.counter_ = 0           # 计数器，可以用来记录已经执行了多少个控制周期
        self.weight = 0.            # 关节控制权重，数值越大控制效果越明显，初始是0.2，可以根据需要调整，调大可以让动作更明显，但对通信和控制性能要求更高，建议先调小测试。
        self.weight_rate = 0.2      # 关节控制权重增加速率，数值越大权重增加越快，初始是0.2，可以根据需要调整，调大可以让动作更快达到目标，但对通信和控制性能要求更高，建议先调小测试。
        self.kp = 60.               # 比例控制系数，表示靠近目标的力度
        self.kd = 1.5               # 微分控制系数，表示抵抗干扰的力度
        self.dq = 0.                # 期望关节速度
        self.tau_ff = 0.            # 前馈力矩，
        self.mode_machine_ = 0      # 运动状态机，初始是0，可以根据需要设计不同的状态机逻辑来实现复杂动作，例如可以设计一个状态机在不同时间段执行不同的动作，或者根据传感器数据切换动作等。
        self.low_cmd = unitree_hg_msg_dds__LowCmd_()   # 低级控制命令消息对象，用来存储要发送的控制命令，初始是一个空的LowCmd_对象，可以根据需要设置其中的字段来控制机器人，例如设置motor_cmd字段来控制关节位置、速度、力矩等。
        self.low_state = None       # 低级状态消息对象，用来存储接收到的机器人状态信息，初始是None，表示还没有接收到状态消息，可以在LowStateHandler中更新这个对象来获取最新的状态信息，例如关节位置、速度、电流等。
        self.first_update_low_state = False            # 是否已经第一次更新低级状态，初始是False，表示还没有接收到状态消息，可以在LowStateHandler中设置为True来表示已经接收到状态消息，这样就可以在Start函数中等待直到接收到状态消息后再开始控制循环，确保有最新的状态信息来进行控制。
        self.crc = CRC()            # CRC校验对象，用来计算控制命令的CRC值，确保通信的可靠性，初始是一个CRC对象，可以在LowCmdWrite中使用这个对象的Crc方法来计算low_cmd的CRC值，并设置到low_cmd.crc字段中，这样机器人在接收到命令时就可以验证命令的完整性。
        self.done = False           # 是否完成整个动作，初始是False，表示还没有完成，可以在LowCmdWrite中根据时间和状态机逻辑设置为True来表示已经完成整个动作，这样在主循环中就可以退出程序。
        self.motion_mode_selected = False
        
        # 定义目标关节位置，单位是弧度，顺序按照下面的arm_joints列表的顺序，其他关节不控制，kPi_2约为90度，kPi约为180度
        # 可以自定义其他动作
        '''
        self.target_pos = [
            0., 0., 0., 0., 0., 0., 0.,
            0.282999, -0.195499, 0.050442, 0.838560, 0.041573, -0.003188, -0.104490, 
            0, 0, 0
        ]'''
        self.target_pos = [
    0.22,
    0.08,
    -0.08,
    1.005,
    0.,
    0.,
    0.,
    -0.896540,
    -0.394676,
    0.618590,
    -0.422863,
    0.574584,
    -0.595999,
    0.438683,
    0.,
    0.,
    -0.08
]
        # 控制的手臂关节 左臂7+右臂7+腰部3=17个关节，顺序按照上面target_pos的顺序，其他关节不控制
        
        self.arm_joints = [
          G1JointIndex.LeftShoulderPitch,  G1JointIndex.LeftShoulderRoll,
          G1JointIndex.LeftShoulderYaw,    G1JointIndex.LeftElbow,
          G1JointIndex.LeftWristRoll,      G1JointIndex.LeftWristPitch,
          G1JointIndex.LeftWristYaw,
          G1JointIndex.RightShoulderPitch, G1JointIndex.RightShoulderRoll,
          G1JointIndex.RightShoulderYaw,   G1JointIndex.RightElbow,
          G1JointIndex.RightWristRoll,     G1JointIndex.RightWristPitch,
          G1JointIndex.RightWristYaw,
          G1JointIndex.WaistYaw,
          G1JointIndex.WaistRoll,
          G1JointIndex.WaistPitch
        ]
        

    # 建立通信接口，创建发布者和订阅者，并进行必要的初始化，例如注册消息类型、设置回调函数等。这个函数在主函数中被调用一次，用来准备好通信环境，确保后续的控制命令能够正确发送和状态信息能够正确接收。
    def Init(self):
        self.msc = MotionSwitcherClient()
        self.msc.SetTimeout(5.0)
        self.msc.Init()

        # create publisher # 往 rt/arm_sdk 发布手臂控制命令。
        self.arm_sdk_publisher = ChannelPublisher("rt/arm_sdk", LowCmd_)
        self.arm_sdk_publisher.Init()

        # create subscriber # 订阅 rt/lowstate，获取当前关节状态。
        self.lowstate_subscriber = ChannelSubscriber("rt/lowstate", LowState_)
        self.lowstate_subscriber.Init(self.LowStateHandler, 10)
    
    # 启动循环控制线程
    def Start(self):
        # 意思是每隔 control_dt_ 执行一次：self.LowCmdWrite()，这个函数是控制循环的核心，在这个函数中会根据时间和状态机逻辑来设置low_cmd的字段，从而控制机器人的动作。通过RecurrentThread来实现定时执行LowCmdWrite函数，这样就可以按照设定的控制频率来发送控制命令。同时在Start函数中还会等待直到第一次接收到低级状态消息，这样就可以确保有最新的状态信息来进行控制，避免在没有状态信息的情况下就开始发送命令。
        self.lowCmdWriteThreadPtr = RecurrentThread(
            interval=self.control_dt_, target=self.LowCmdWrite, name="control"
        )
        while self.first_update_low_state == False:
            time.sleep(1)

        if self.first_update_low_state == True:
            self.lowCmdWriteThreadPtr.Start()
    # 接收机器人状态消息的回调函数，每当接收到新的状态消息时，这个函数就会被调用，并且参数msg就是最新的状态消息对象。在这个函数中，我们将接收到的状态消息存储到self.low_state中，这样就可以在控制循环中使用最新的状态信息来进行控制。同时我们还设置了self.first_update_low_state为True，表示已经接收到状态消息，这样在Start函数中就可以等待直到接收到状态消息后再开始控制循环，确保有最新的状态信息来进行控制。
    def LowStateHandler(self, msg: LowState_):
        self.low_state = msg
        if self.first_update_low_state == False:
            self.first_update_low_state = True
    # 真正执行动作，每 20ms 执行一次，负责：计算当前时刻应该发什么关节角度，把命令写到 low_cmd，计算 CRC，发布到 rt/arm_sdk
    '''
    def LowCmdWrite(self):
        self.time_ += self.control_dt_

        if self.time_ < self.duration_ :
          # [Stage 1]: set robot to zero posture
          self.low_cmd.motor_cmd[G1JointIndex.kNotUsedJoint].q =  1 # 1:Enable arm_sdk, 0:Disable arm_sdk
          for i,joint in enumerate(self.arm_joints):
            ratio = np.clip(self.time_ / self.duration_, 0.0, 1.0)
            self.low_cmd.motor_cmd[joint].tau = 0. 
            self.low_cmd.motor_cmd[joint].q = (1.0 - ratio) * self.low_state.motor_state[joint].q 
            self.low_cmd.motor_cmd[joint].dq = 0. 
            self.low_cmd.motor_cmd[joint].kp = self.kp 
            self.low_cmd.motor_cmd[joint].kd = self.kd

        elif self.time_ < self.duration_ * 3 :
          # [Stage 2]: lift arms up
          for i,joint in enumerate(self.arm_joints):
              ratio = np.clip((self.time_ - self.duration_) / (self.duration_ * 2), 0.0, 1.0)
              self.low_cmd.motor_cmd[joint].tau = 0. 
              self.low_cmd.motor_cmd[joint].q = ratio * self.target_pos[i] + (1.0 - ratio) * self.low_state.motor_state[joint].q 
              self.low_cmd.motor_cmd[joint].dq = 0. 
              self.low_cmd.motor_cmd[joint].kp = self.kp 
              self.low_cmd.motor_cmd[joint].kd = self.kd

        elif self.time_ < self.duration_ * 6 :
          # [Stage 3]: set robot back to zero posture
          for i,joint in enumerate(self.arm_joints):
              ratio = np.clip((self.time_ - self.duration_*3) / (self.duration_ * 3), 0.0, 1.0)
              self.low_cmd.motor_cmd[joint].tau = 0. 
              self.low_cmd.motor_cmd[joint].q = (1.0 - ratio) * self.low_state.motor_state[joint].q
              self.low_cmd.motor_cmd[joint].dq = 0. 
              self.low_cmd.motor_cmd[joint].kp = self.kp 
              self.low_cmd.motor_cmd[joint].kd = self.kd

        elif self.time_ < self.duration_ * 7 :
          # [Stage 4]: release arm_sdk
          for i,joint in enumerate(self.arm_joints):
              ratio = np.clip((self.time_ - self.duration_*6) / (self.duration_), 0.0, 1.0)
              self.low_cmd.motor_cmd[G1JointIndex.kNotUsedJoint].q =  (1 - ratio) # 1:Enable arm_sdk, 0:Disable arm_sdk
        
        else:
            self.done = True
  
        self.low_cmd.crc = self.crc.Crc(self.low_cmd)
        self.arm_sdk_publisher.Write(self.low_cmd)
    '''
    def LowCmdWrite(self):
        self.time_ += self.control_dt_

        if self.time_ < self.duration_ * 2:
          # [Stage 1]: lift arms up directly
          self.low_cmd.motor_cmd[G1JointIndex.kNotUsedJoint].q = 1 # 1:Enable arm_sdk, 0:Disable arm_sdk
          for i, joint in enumerate(self.arm_joints):
              ratio = np.clip(self.time_ / (self.duration_ * 2), 0.0, 1.0)
              self.low_cmd.motor_cmd[joint].tau = 0.
              if joint in (G1JointIndex.WaistYaw, G1JointIndex.WaistRoll, G1JointIndex.WaistPitch):
                  self.low_cmd.motor_cmd[joint].q = self.target_pos[i]
              else:
                  self.low_cmd.motor_cmd[joint].q = ratio * self.target_pos[i] + (1.0 - ratio) * self.low_state.motor_state[joint].q
              self.low_cmd.motor_cmd[joint].dq = 0.
              self.low_cmd.motor_cmd[joint].kp = self.kp
              self.low_cmd.motor_cmd[joint].kd = self.kd

        elif self.time_ < self.duration_ * 3:
          # [Stage 2]: release arm_sdk
          ratio = np.clip((self.time_ - self.duration_ * 2) / self.duration_, 0.0, 1.0)
          self.low_cmd.motor_cmd[G1JointIndex.kNotUsedJoint].q = 1.0 - ratio # 1:Enable arm_sdk, 0:Disable arm_sdk

        #当动作时间超过 duration_ * 3 后：
        #关闭 arm_sdk 控制，发送最后一帧控制命令，等 0.5 秒，切回 normal 模式标记动作完成，退出控制函数
        else:
            self.low_cmd.motor_cmd[G1JointIndex.kNotUsedJoint].q = 0.0
            if not self.motion_mode_selected:
                self.low_cmd.crc = self.crc.Crc(self.low_cmd)
                self.arm_sdk_publisher.Write(self.low_cmd)
                time.sleep(0.5)
                ret = self.msc.SelectMode("normal")
                print("Select normal mode ret:", ret)
                self.motion_mode_selected = True
            self.done = True
            return

        self.low_cmd.crc = self.crc.Crc(self.low_cmd)
        self.arm_sdk_publisher.Write(self.low_cmd)
    
    
if __name__ == '__main__':

    print("WARNING: Please ensure there are no obstacles around the robot while running this example.")
    input("Press Enter to continue...")

    if len(sys.argv)>1:
        ChannelFactoryInitialize(0, sys.argv[1])
    else:
        ChannelFactoryInitialize(0)

    custom = Custom()
    custom.Init()
    custom.Start()

    while True:        
        time.sleep(1)
        if custom.done: 
           print("Done!")
           sys.exit(-1)    
