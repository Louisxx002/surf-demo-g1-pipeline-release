function  test

[msig, fs]          = audioread('mixture.wav');
DCF_Targ_Filter     = importdata('DCF_Targ7.mat');
 
outsig              =  Fixed_Mini_Beamformer(msig, DCF_Targ_Filter, fs);

audiowrite('out0.wav', outsig, fs);