import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import os
import subprocess
import requests
import threading

from project_config import CONFIG


HTTP_SESSION = requests.Session()
HTTP_SESSION.trust_env = False


class QwenAudioNode(Node):
    def __init__(self):
        super().__init__('qwen_audio_node')
        self.force_always_listen = CONFIG.always_listen
        self.awaiting_command_after_wake = False

        # ✅ ROS订阅
        self.sub = self.create_subscription(
            String,
            CONFIG.ros_audio_topic,
            self.callback,
            10
        )

        CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)

        self.get_logger().info("ROS2 Audio Node ready (HTTP -> Qwen -> wav)")
        self.get_logger().info(f"ASR topic: {CONFIG.ros_audio_topic}")
        self.get_logger().info(f"Qwen server: {CONFIG.qwen_server_url}")
        self.get_logger().info(f"Wake words: {', '.join(CONFIG.wake_words)}")
        self.get_logger().info(
            "Reply action bridge: "
            f"enabled={CONFIG.action_enable}, execute={CONFIG.action_execute}, "
            f"backend={CONFIG.action_backend}, network={CONFIG.unitree_network_interface}"
        )
        if self.force_always_listen:
            self.get_logger().info("Plain listen mode is enabled. Every /audio_msg text will be handled.")
        else:
            self.get_logger().info("Wake-word mode is enabled. Say a wake word before each command.")
        self.get_logger().info("Keyboard: type 'start' for plain listen mode, 'wake' for wake-word mode, or 'quit' to exit.")

        self.control_thread = threading.Thread(target=self.keyboard_control_loop, daemon=True)
        self.control_thread.start()

    def keyboard_control_loop(self):
        while rclpy.ok():
            try:
                command = input().strip().lower()
            except EOFError:
                return
            except KeyboardInterrupt:
                return

            if command in ("", "wake", "wakeup"):
                self.force_always_listen = False
                self.awaiting_command_after_wake = False
                self.get_logger().info("Wake-word mode enabled.")
            elif command in ("start", "always", "always-on"):
                self.force_always_listen = True
                self.awaiting_command_after_wake = False
                self.get_logger().info("Plain listen mode enabled.")
            elif command in ("quit", "exit"):
                self.get_logger().info("Exit requested from keyboard.")
                rclpy.shutdown()
                return
            else:
                self.get_logger().info("Type 'wake', 'start', or 'quit'.")

    @staticmethod
    def strip_wake_word(text):
        lowered_text = text.lower()
        for wake_word in CONFIG.wake_words:
            index = lowered_text.find(wake_word.lower())
            if index < 0:
                continue

            prefix = text[:index]
            suffix = text[index + len(wake_word):]
            return (prefix + suffix).strip("，,。.!！?？ ")

        # Some ASR engines insert spaces inside short wake words, for example
        # "小 g". Fall back to a compact check for those cases.
        compact_text = text.replace(" ", "")
        for wake_word in CONFIG.wake_words:
            compact_wake = wake_word.replace(" ", "")
            index = compact_text.lower().find(compact_wake.lower())
            if index < 0:
                continue

            if index == 0:
                return compact_text[len(compact_wake):].strip("，,。.!！?？ ")

            prefix = compact_text[:index]
            suffix = compact_text[index + len(compact_wake):]
            return (prefix + suffix).strip("，,。.!！?？ ")

        return None

    def callback(self, msg):
        raw = msg.data

        try:
            data = json.loads(raw)
            user_text = data.get("text", "")
        except Exception:
            user_text = raw.strip()

        if not user_text:
            return

        self.get_logger().info(f"ASR text: {user_text}")

        if not self.force_always_listen:
            command_text = self.strip_wake_word(user_text)
            if command_text is None:
                if not self.awaiting_command_after_wake:
                    self.get_logger().info("Wake word not detected, ignoring this ASR text.")
                    return
                command_text = user_text.strip()
                self.awaiting_command_after_wake = False
            elif not command_text:
                self.awaiting_command_after_wake = True
                self.get_logger().info("Wake word detected. Waiting for the next command.")
                return
            user_text = command_text
            self.get_logger().info(f"Command after wake word: {user_text}")

        # ⭐ 调 Qwen 服务
        try:
            r = HTTP_SESSION.get(
                CONFIG.qwen_server_url,
                params={"text": user_text},
                timeout=CONFIG.request_timeout_sec
            )
            r.raise_for_status()
            result = r.json()
            reply = result.get("reply", "")
        except Exception as e:
            self.get_logger().error(f"Qwen request failed: {e}")
            return

        if not reply:
            self.get_logger().error("Empty reply from Qwen")
            return

        self.get_logger().info(f"Qwen reply: {reply}")

        # ⭐ 等待 tts.mp3 出现
        if not CONFIG.tts_mp3_path.exists():
            self.get_logger().error(f"{CONFIG.tts_mp3_path} not found (Qwen server did not generate it)")
            return

        # ⭐ 转 wav
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(CONFIG.tts_mp3_path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(CONFIG.tts_wav_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self.get_logger().error(f"ffmpeg conversion failed: {e}")
            return

        if not CONFIG.tts_wav_path.exists():
            self.get_logger().error(f"{CONFIG.tts_wav_path} not generated")
            return

        self.get_logger().info(f"TTS wav generated successfully: {CONFIG.tts_wav_path}")
        self.run_reply_action(reply)

    def run_reply_action(self, reply):
        if not CONFIG.action_enable:
            return

        command = [
            CONFIG.action_python,
            str(CONFIG.action_script),
            reply,
            "--backend",
            CONFIG.action_backend,
            "--threshold",
            str(CONFIG.action_threshold),
            "--network",
            CONFIG.unitree_network_interface,
            "--runner",
            str(CONFIG.action_runner),
        ]
        if CONFIG.action_execute:
            command.append("--execute")

        try:
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                timeout=90,
                env=self.action_env(),
            )
        except Exception as exc:
            self.get_logger().error(f"Reply action bridge failed: {exc}")
            return

        if completed.stderr:
            self.get_logger().warn(f"Reply action stderr: {completed.stderr.strip()}")

        try:
            payload = json.loads(completed.stdout)
        except Exception:
            self.get_logger().error(
                "Reply action returned non-JSON output: "
                f"returncode={completed.returncode}, stdout={completed.stdout.strip()}"
            )
            return

        classification = payload.get("classification", {})
        execution = payload.get("execution", {})
        self.get_logger().info(
            "Reply action: "
            f"{classification.get('label')} / {classification.get('official_name')} "
            f"id={classification.get('action_id')} "
            f"score={classification.get('score')} "
            f"backend={classification.get('backend')} "
            f"executed={execution.get('executed')} "
            f"reason={execution.get('reason')}"
        )
        if not execution.get("executed"):
            stdout = str(execution.get("stdout", "")).strip()
            stderr = str(execution.get("stderr", "")).strip()
            returncode = execution.get("returncode")
            if stdout:
                self.get_logger().warn(f"Reply action runner stdout: {stdout}")
            if stderr:
                self.get_logger().warn(f"Reply action runner stderr: {stderr}")
            if returncode is not None:
                self.get_logger().warn(f"Reply action runner returncode: {returncode}")

        if (
            CONFIG.action_auto_release
            and CONFIG.action_execute
            and execution.get("reason") == "arm_holding_release_required"
        ):
            self.get_logger().warn("Arm is holding; running release action 99 and retrying once.")
            if self.release_arm():
                self.retry_reply_action(command)

    @staticmethod
    def action_env():
        env = os.environ.copy()
        env["NO_PROXY"] = "127.0.0.1,localhost," + env.get("NO_PROXY", "")
        env["no_proxy"] = "127.0.0.1,localhost," + env.get("no_proxy", "")
        sdk_root = CONFIG.action_runner.parent.parent.parent
        unitree_lib_dir = sdk_root / "thirdparty" / "lib" / os.uname().machine
        if unitree_lib_dir.is_dir():
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = str(unitree_lib_dir) + (f":{existing}" if existing else "")
        return env

    def release_arm(self):
        env = self.action_env()
        try:
            completed = subprocess.run(
                [
                    str(CONFIG.action_runner),
                    "--network",
                    CONFIG.unitree_network_interface,
                    "--id",
                    "99",
                ],
                check=False,
                text=True,
                capture_output=True,
                timeout=20,
                env=env,
            )
        except Exception as exc:
            self.get_logger().error(f"Release arm action failed: {exc}")
            return False

        if completed.stdout:
            self.get_logger().info(f"Release arm stdout: {completed.stdout.strip()}")
        if completed.stderr:
            self.get_logger().warn(f"Release arm stderr: {completed.stderr.strip()}")
        return completed.returncode == 0

    def retry_reply_action(self, command):
        try:
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                timeout=90,
                env=self.action_env(),
            )
        except Exception as exc:
            self.get_logger().error(f"Reply action retry failed: {exc}")
            return

        try:
            payload = json.loads(completed.stdout)
        except Exception:
            self.get_logger().error(f"Reply action retry returned non-JSON output: {completed.stdout.strip()}")
            return

        classification = payload.get("classification", {})
        execution = payload.get("execution", {})
        self.get_logger().info(
            "Reply action retry: "
            f"{classification.get('label')} id={classification.get('action_id')} "
            f"executed={execution.get('executed')} reason={execution.get('reason')}"
        )


def main():
    rclpy.init()

    node = QwenAudioNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
