import nidaqmx
import matplotlib.pyplot as plt
import time
from nidaqmx.constants import TerminalConfiguration

#setup NI DAQ
task = nidaqmx.Task()
task.ai_channels.add_ai_voltage_chan("Dev1/ai0", terminal_config=TerminalConfiguration.DIFFERENTIAL)

#setup plot
plt.ion()
figure, axis = plt.subplots()
xData = []
yData = []
line, = axis.plot(xData, yData)
axis.set_xlabel("time")
axis.set_ylabel("voltage")
axis.set_ylim(0,5)

print("Startup")
initialTime = time.time()
try:
    while(True):
        data = task.read()
        yData.append(data)
        xData.append(time.time())
        line.set_xdata(xData)
        line.set_ydata(yData)
        axis.relim()
        axis.autoscale_view()
        plt.pause(0.05)
except:
    print("Shutting Down")
finally:
    task.close()
    print("Shutdown Complete")