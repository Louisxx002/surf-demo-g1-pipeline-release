function mSig = Fixed_Mini_Beamformer(inputSig, SG_Null_Filter, fs)
% 任意阵列 MVDR + RLS based Postfilter
% 点源干扰估计基于概率空间相关矩阵
% 输入说明：
% 1. inputSig: 带噪麦克风阵列数据
% 2. SG_Null_Filter: 阻塞滤波器：
% 3. fs: 音频的采样频率
% 输出说明：
% 1. mSig: 阻塞输出
%% 参数设置
%alpha_y_post = 0.72;    % 观测信号协方差追踪平滑系数（用于计算信号与点干扰能量的比值）

%% 输入检查
if nargin<1
    disp('noiSpeech is missing!');
    return;
end
if nargin<2
    disp('Filter is missing!');
    return;
end
if nargin<3
    disp('Defaulting sampling frequency is set as: 16KHz');
    fs = 16000;
end

[nLen, nChan]          = size(inputSig);
[nChan, nFreq, nNull]  = size(SG_Null_Filter);

%% STFT设置
wLen                  = floor(32*fs/1000);
hammingWin            = zeros(wLen,nChan);
for n = 1:nChan
    hammingWin(:, n)  =  sin((.5:wLen-.5)/wLen*pi).';
end
overlap               = 0.5;
len1                  = floor(wLen*overlap);
len2                  = wLen - len1; %Step shift
nFrame                = floor((nLen-wLen)/len2);
nFFT                  = wLen;

synWin                = hammingWin(:, 1); 
numFreq               =  wLen/2+1;

%% 初始化参数
mSig                  = zeros(nLen, 1);
mSpec                 = zeros(numFreq, nNull);

mSpecm                = zeros(numFreq, nNull);
mPower                = zeros(nNull, 1);

miu                   = 0.15;
Low_Frq               = 20;
High_Frq              = 80;

%%------------开始处理------------------%%
nStart = 1;
for iFrame = 1:nFrame
    yOneFrame   = inputSig(nStart:nStart+wLen-1,:);
	ySpec       = fft(yOneFrame.*hammingWin,nFFT);
    for iFreq   = 2 : numFreq
        % % Beamforming
        for k = 1:nNull
            SG_Vec_T          = reshape(SG_Null_Filter(:, iFreq, k) , nChan, 1);
            mSpec(iFreq,k)    = SG_Vec_T'*ySpec(iFreq,:).'; 
        end
    end
    mSpecm                    = miu*mSpecm  + (1-miu)*abs(mSpec).^(2);
    
    for k = 1:nNull
        mPower(k) =  sum(mSpecm(Low_Frq:High_Frq, k));
    end
    k_Flag        = find(mPower == min(mPower));

    %DeFlag(iFrame) = k_Flag(1);
    mSig(nStart:nStart+wLen-1, 1) = mSig(nStart:nStart+wLen-1,1)+  ...
                                      synWin.*real(ifft( [mSpec(:,k_Flag(1));conj(mSpec(end-1:-1:2,k_Flag(1)))]));
  
	nStart = nStart+len2;
end
% figure
% plot(DeFlag)
