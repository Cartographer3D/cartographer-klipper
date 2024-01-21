# 打开文件
from scipy.optimize import curve_fit
import numpy as np
import matplotlib.pyplot as plt
class TempModel:
    def __init__(self, a_a, a_b, b_a, b_b, fmin, fmin_temp):
        self.a_a=a_a
        self.a_b=a_b
        self.b_a=b_a
        self.b_b=b_b
        self.fmin = fmin
        self.fmin_temp = fmin_temp

    def compensate(self, freq, temp_source, temp_target):
        if self.a_a == None or self.a_b == None or self.b_a == None or self.b_b == None:
            return freq
        if(self.a_a==self.a_b==0):
            param_b=param_linear(freq-model.fmin,self.b_a,self.b_b)
            return freq-param_b*temp_source+param_b*temp_target
        A=4*(temp_source*self.a_a)**2+4*temp_source*self.a_a*self.b_a+self.b_a**2+4*self.a_a
        B=8*temp_source**2*self.a_a*self.a_b+4*temp_source*(self.a_a*self.b_b+self.a_b*self.b_a)+2*self.b_a*self.b_b+4*self.a_b-4*(freq-model.fmin)*self.a_a
        C=4*(temp_source*self.a_b)**2+4*temp_source*self.a_b*self.b_b+self.b_b**2-4*(freq-model.fmin)*self.a_b
        if(B**2-4*A*C<0):
            param_c=freq-param_linear(freq-model.fmin,self.a_a,self.a_b)*temp_source**2-param_linear(freq-model.fmin,self.b_a,self.b_b)*temp_source
            return param_linear(freq-model.fmin,self.a_a,self.a_b)*temp_target**2+param_linear(freq-model.fmin,self.b_a,self.b_b)*temp_target+param_c
        ax=(np.sqrt(B**2-4*A*C)-B)/2/A
        param_a=param_linear(ax,self.a_a,self.a_b)
        param_b=param_linear(ax,self.b_a,self.b_b)
        return param_a*(temp_target+param_b/2/param_a)**2+ax+model.fmin
        #print(-param_linear(ax,self.b_a,self.b_b)/2/param_linear(ax,self.a_a,self.a_b))
        #param_c=freq-param_linear(freq-model.fmin,self.a_a,self.a_b)*temp_source**2-param_linear(freq-model.fmin,self.b_a,self.b_b)*temp_source
        #return param_linear(freq-model.fmin,self.a_a,self.a_b)*temp_target**2+param_linear(freq-model.fmin,self.b_a,self.b_b)*temp_target+param_c
def line_fit(x,a,b,c):
    return a*x**2+b*x+c

def area_find(temp,freq):
    middle=int(len(temp)/100/2)*100
    i=j=100
    i_flag=True
    j_flag=True
    for c in range(100):
        if(i_flag):
            i=i+100
            if middle-i>=0:
                linear_params, params_covariance = curve_fit(line_fit, temp[middle-i:middle+j],freq[middle-i:middle+j],maxfev=100000,ftol=1e-10,xtol=1e-10)
                minus=line_fit(temp[middle-i:middle+j],linear_params[0],linear_params[1],linear_params[2])-freq[middle-i:middle+j]
            if np.sum(np.square(minus))/len(minus)>threshold:
                i=i-100
                i_flag=False
        if(j_flag):
            j=j+100
            if middle+j<=len(freq):
                linear_params, params_covariance = curve_fit(line_fit, temp[middle-i:middle+j],freq[middle-i:middle+j],maxfev=100000,ftol=1e-10,xtol=1e-10)
                minus=line_fit(temp[middle-i:middle+j],linear_params[0],linear_params[1],linear_params[2])-freq[middle-i:middle+j]
            if np.sum(np.square(minus))/len(minus)>threshold:
                j=j-100
                j_flag=False
    linear_params, params_covariance = curve_fit(line_fit, temp[middle-i:middle+j],freq[middle-i:middle+j],maxfev=100000,ftol=1e-10,xtol=1e-10)
    return linear_params
def data_process(path):
    freq=[]
    temp=[]
    with open(path, 'r') as file:
        # 逐行读取文件内容
        lines = file.readlines()
        # 遍历每行内容
        for line in lines:
            data=line.split(',')
            try:
                freq.append(float(data[3]))
                temp.append(float(data[5]))
            except:pass
    dv=int(len(temp)/1000)
    if dv>1:
        freq=np.array(freq[::dv])
        temp=np.array(temp[::dv])
    plt.plot(temp[20:],freq[20:])
    #linear_params=area_find(temp[20:],freq[20:])
    param_bounds=([0,-np.inf,-np.inf],[100,np.inf,np.inf])
    linear_params, params_covariance = curve_fit(line_fit, temp[20:],freq[20:],bounds=param_bounds,maxfev=100000,ftol=1e-10,xtol=1e-10)
    plt.plot(temp[20:],line_fit(temp[20:],linear_params[0],linear_params[1],linear_params[2]))
    try:
        plt.title("Range:"+str(int(np.max(freq[20:])-np.min(freq[20:]))))
    except:
        pass
    axis=-1*linear_params[1]/2/linear_params[0]
    if(axis>120):
        linear_params1, params_covariance = curve_fit(param_linear, temp[20:],freq[20:],maxfev=100000,ftol=1e-10,xtol=1e-10)
        axis=120
        return [0,linear_params1[0],param_linear(axis,linear_params1[0],linear_params1[1])]
    linear_params[2]=line_fit(axis,linear_params[0],linear_params[1],linear_params[2])
    return linear_params
def param_linear(x,a,b):
    return a*x+b
while(1):
    plt.figure(figsize=(25, 15))
    paths=['./data1','./data2','./data3','./data4']
    a=[]
    b=[]
    freqs=[]
    num=241
    #threshold=int(input('threshold set(recommend start from 1000):\n请输入阈值设置(默认推荐1000):\n'))
    try:
        for path in paths:
            plt.subplot(num)
            num+=1
            temp=data_process(path)
            a.append(temp[0])
            b.append(temp[1])
            freqs.append(temp[2])
    except:
        print("please make sure you have move the 4 data file to IDM folder\n请确认你有把4个文件拷到IDM文件夹内")
        break
    #反向求值
    model=TempModel(None,None,None,None,2943053,23.33)
    param_bounds_a=([0,-np.inf],[np.inf,np.inf])
    if(np.sum(np.array(a)==0)==4):
        model.a_a=0
        model.a_b=0
        linear_params1, params_covariance = curve_fit(param_linear, np.array(freqs)-model.fmin,b,maxfev=100000,ftol=1e-10,xtol=1e-10)
    else:
        linear_params, params_covariance = curve_fit(param_linear, np.array(freqs)-model.fmin,a,bounds=param_bounds_a,maxfev=100000,ftol=1e-10,xtol=1e-10)
        model.a_a=linear_params[0]
        model.a_b=linear_params[1]
        param_bounds_b=([-np.inf,-np.inf],[0,np.inf])
        linear_params1, params_covariance = curve_fit(param_linear, np.array(freqs)-model.fmin,b,bounds=param_bounds_b,maxfev=100000,ftol=1e-10,xtol=1e-10)
    model.b_a=linear_params1[0]
    model.b_b=linear_params1[1]
    for path in paths:
        plt.subplot(num)
        num+=1
        freq=[]
        temp=[]
        with open(path, 'r') as file:
            # 逐行读取文件内容
            lines = file.readlines()
            # 遍历每行内容
            for line in lines:
                data=line.split(',')
                try:
                    freq.append(float(data[3]))
                    temp.append(float(data[5]))
                except:pass
        dv=int(len(temp)/10000)
        if dv>1:
            freq=np.array(freq[::dv])
            temp=np.array(temp[::dv])
        temp=temp[200:]
        freq=freq[200:]
        result0=[]
        for i in range(len(temp)):
            result0.append(model.compensate(freq[i],temp[i],50))
        plt.plot(temp,result0)
        try:
            plt.title("Range:"+str(int(np.max(result0)-np.min(result0))))
        except:
            pass
    plt.savefig('fit_output.png')
    print('fit result:')
    print('tc_a_a:'+str(model.a_a)+'\ntc_a_b:'+str(model.a_b)+'\ntc_b_a:'+str(model.b_a)+'\ntc_b_b:'+str(model.b_b))
    break