from scipy.optimize import curve_fit
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import warnings
warnings.filterwarnings("ignore")
class TempModel:
    def __init__(self, amfg, tcc, tcfl, tctl, fmin, fmin_temp):
        self.amfg = amfg
        self.tcc = tcc
        self.tcfl = tcfl
        self.tctl = tctl
        self.fmin = fmin
        self.fmin_temp = fmin_temp

    def _tcf(self, f, df, dt, tctl):
        tctl = self.tctl if tctl is None else tctl
        tc = self.tcc + self.tcfl * df + tctl * df * df
        return f + self.amfg * tc * dt * f

    def compensate(self, freq, temp_source, temp_target, tctl=None):
        dt = temp_target - temp_source
        dfmin = self.fmin * self.amfg * self.tcc * \
                (temp_source - self.fmin_temp)
        df = freq - (self.fmin + dfmin)
        if dt < 0.:
            f2 = self._tcf(freq, df, dt, tctl)
            dfmin2 = self.fmin * self.amfg * self.tcc * \
                    (temp_target - self.fmin_temp)
            df2 = f2 - (self.fmin + dfmin2)
            f3 = self._tcf(f2, df2, -dt, tctl)
            ferror = freq - f3
            freq = freq + ferror
            df = freq - (self.fmin + dfmin)
        return self._tcf(freq, df, dt, tctl)
def line_fit(x,a,b,c):
    return a*x**2+b*x+c
def fit(data,tcc,tcfl,tctl):
    result=[]
    model.tcc=tcc
    model.tcfl=tcfl
    model.tctl-tctl
    for j in range(len(datas)):
        for i in range(len(data)):
            result.append(model.compensate(datas[j][3000],35,data[i]))
    return result
def area_find(temp,freq):
    middle=int(len(temp)/100/2)*100
    i=j=100
    i_flag=True
    j_flag=True
    for c in range(100):
        if(i_flag):
            i=i+100
            if middle-i>=0:
                linear_params, params_covariance = curve_fit(line_fit, temp[middle-i:middle+j],freq[middle-i:middle+j],maxfev=100000,ftol=1e-10,xtol=1e-20)
                minus=line_fit(temp[middle-i:middle+j],linear_params[0],linear_params[1],linear_params[2])-freq[middle-i:middle+j]
            if np.sum(np.square(minus))/len(minus)>threshold:
                i=i-100
                i_flag=False
        if(j_flag):
            j=j+100
            if middle+j<=len(freq):
                linear_params, params_covariance = curve_fit(line_fit, temp[middle-i:middle+j],freq[middle-i:middle+j],maxfev=100000,ftol=1e-10,xtol=1e-20)
                minus=line_fit(temp[middle-i:middle+j],linear_params[0],linear_params[1],linear_params[2])-freq[middle-i:middle+j]
            if np.sum(np.square(minus))/len(minus)>threshold:
                j=j-100
                j_flag=False
    linear_params, params_covariance = curve_fit(line_fit, temp[middle-i:middle+j],freq[middle-i:middle+j],maxfev=100000,ftol=1e-10,xtol=1e-20)
    return linear_params
def data_process(path):
    data=[]
    file_path = path  
    with open(file_path, 'r') as file:
        lines = file.readlines()
        for line in lines:
            data.append(line.split(','))
    file.close()
    full_data=pd.DataFrame(data[1:-1],columns=data[0])
    temp=np.array(full_data['temp']).astype(np.float32)
    freq=np.array(full_data['freq']).astype(np.float32)
    freq=freq[::100]
    temp=temp[::100]
    plt.plot(temp[10:],freq[10:])
    linear_params=area_find(temp,freq)
    plt.plot(temp,line_fit(temp,linear_params[0],linear_params[1],linear_params[2]))
    data0=line_fit(np.arange(5,80,0.01),linear_params[0],linear_params[1],linear_params[2])
    return data0
while(1):
    plt.figure(figsize=(25, 15))
    paths=['./data1','./data2','./data3','./data4']
    datas=[]
    num=241
    threshold=int(input('threshold set(recommend start from 250):'))
    try:
        for path in paths:
            plt.subplot(num)
            num+=1
            datas.append(data_process(path))
    except:
        print("please make sure you have move the 4 data file to Cartographer folder")
        break
    model=TempModel(1,-2.1429828e-05,-1.8980091e-10,3.6738370e-16,2943053.84,20.33)
    p0=[-2.1429828e-05,-1.8980091e-10,3.6738370e-16]
    params, params_covariance = curve_fit(fit,np.arange(5,80,0.01),np.hstack(datas),p0=p0,maxfev=1000000,ftol=1e-10,xtol=1e-10)
    for path in paths:
        plt.subplot(num)
        num+=1
        data=[]
        file_path = path 
        with open(file_path, 'r') as file:
            lines = file.readlines()
            for line in lines:
                data.append(line.split(','))
        file.close()
        full_data=pd.DataFrame(data[1:-1],columns=data[0])
        temp=np.array(full_data['temp']).astype(np.float32)
        freq=np.array(full_data['freq']).astype(np.float32)
        freq=freq[::100]
        temp=temp[::100]
        result0=[]
        for i in range(len(temp)):
            result0.append(model.compensate(freq[i],temp[i],20.66))
        plt.plot(temp[10:],result0[10:])
    plt.savefig('fit.png')
    print('fit result:')
    print('tc_tcc:'+str(params[0])+'\ntc_tcfl:'+str(params[1])+'\ntc_tctl:'+str(params[2]))
    break