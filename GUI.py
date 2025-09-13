import sys
import time
import random
import queue
import csv
from PyQt5.QtWidgets import QApplication, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QPushButton, QFileDialog, QMessageBox, QGroupBox, QGridLayout, QDialog, QDialogButtonBox, QLineEdit
from PyQt5.QtCore import QThread, QTimer, pyqtSignal, pyqtSlot, Qt
import pyqtgraph as pg
import threading
import json
import math

from nidaqmx.system import System
import nidaqmx
from nidaqmx.constants import AcquisitionType

# === general functions ===

def clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)  # take the first item
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()  # safely delete widget
            else:
                # If it's another layout, clear it recursively
                sub_layout = item.layout()
                if sub_layout is not None:
                    clear_layout(sub_layout)

# ===DAQ general functions===  
def get_system_name_from_daq_name(daq_name: str) -> str:
    if '/' not in daq_name:
        raise ValueError(f"Invalid channel string: {daq_name}")
    return daq_name.split('/', 1)[1]

def make_daq_name(dev_name:str, ch_name:str) -> str:
    return f"{dev_name}/{ch_name}"

def null_config():
    return {
        'device': {
            'model': None, 
            'name': None, 
            'sample_rate': None
            },
        'analog': {},
        'digital': {}
    }

def make_default_config(name: str) -> dict:
    system = System.local()
    dev = system.devices[name]
    config = {'device':{'model': dev.product_type, 'name': dev.name, 'sample_rate': 10}, 'analog':{}, 'digital':{}}
    #detect analog channels
    for ai_channel in list(dev.ai_physical_chans):
        config['analog'][get_system_name_from_daq_name(ai_channel.name)] = {'enabled': False, 'mode': ai_channel.ai_term_cfgs[0].name, 'modes': [ch.name for ch in ai_channel.ai_term_cfgs]}
    #detect digital channels
    for digital_input_channel in dev.di_lines:
        config['digital'][get_system_name_from_daq_name(digital_input_channel.name)] = {'enabled': False, 'mode': 'Input', 'modes': ['Input']}
    for digital_output_channel in dev.do_lines:
        if(digital_output_channel.name in [ch.name for ch in dev.di_lines]):
            config['digital'][get_system_name_from_daq_name(digital_output_channel.name)]['modes'] = ["Input", "Output"]
        else:
            config['digital'][get_system_name_from_daq_name(digital_output_channel.name)] = {'enabled': False, 'mode': 'Output', 'modes': ['Output']}
            
    return config
    
    




# === DAQ Worker Thread (Dummy Data Generator) ===
class DAQWorker(QThread):
    configuration_exception = pyqtSignal(str) 
    def __init__(self, plot_queue, record_queue, record_flag):
        super().__init__()
        self.plot_queue = plot_queue
        self.record_queue = record_queue
        self.record_flag = record_flag
        self.sample_interval = None
        self.active_channels = []
        self.user_input_channels = []
        self.user_inputs = [0 for _ in range(0,8)]
        self.running = False
        self.start_time = 0

        self.analog_task = None
        self.digital_input_task = None
        self.digital_output_task = None

    def run(self):
        self.running = True
        if(self.analog_task):
            self.analog_task.start()
        self.start_time = time.time()
        if(self.digital_input_task):
            self.digital_input_task.start()
        num_analog_samples = 0
        while self.running:
            analog_samples = self.analog_task.read(number_of_samples_per_channel=nidaqmx.constants.READ_ALL_AVAILABLE)
            current_num_analog_samples = 0
            if(analog_samples):
                try:
                    current_num_analog_samples = len(analog_samples[0])
                except TypeError:
                    current_num_analog_samples = 0
            analog_timestamps = [self.sample_interval * i for i in range(num_analog_samples, num_analog_samples + current_num_analog_samples)]
            num_analog_samples =  num_analog_samples + current_num_analog_samples
            if(current_num_analog_samples>0):
                digital_sample = self.digital_input_task.read()
                digital_samples = [[sample] * current_num_analog_samples for sample in digital_sample]
                print("---")
                print(analog_samples)
                print(digital_samples)
                print(analog_timestamps)
            time.sleep(self.sample_interval/2)

    def stop(self):
        self.running = False
        self.wait()

    def update_config(self, config):
        if(self.analog_task):
            self.analog_task.close()
        self.analog_task = nidaqmx.Task()
        for channel in config['analog'].keys():
            if(config['analog'][channel]['enabled']):
                self.analog_task.ai_channels.add_ai_voltage_chan(make_daq_name(config['device']['name'], channel))
        self.analog_task.timing.cfg_samp_clk_timing(rate = config['device']['sample_rate'], sample_mode=AcquisitionType.CONTINUOUS)

        if(self.digital_input_task):
            self.digital_input_task.close()
        self.digital_input_task = nidaqmx.Task()
        for channel in config['digital'].keys():
            if(config['digital'][channel]['enabled'] and config['digital'][channel]['mode'] == 'Input'):
                self.digital_input_task.di_channels.add_di_chan(make_daq_name(config['device']['name'], channel))

        self.sample_interval = 1.0 / config['device']['sample_rate']

        self.user_inputs = {}
        for channel in config['digital'].keys():
            self.active_channels.append(channel)
            if(config['digital'][channel]['enabled'] and config['digital'][channel]['mode'] == 'Input'):
                self.user_inputs[channel] = 0
            

    def user_input(self, channel, value):
        self.user_inputs[channel] = value  

class DeviceSelectDialog(QDialog):
    def __init__(self, allowed_types=None, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Select DAQ Device")
        layout = QVBoxLayout(self)

        # Device list
        self.combo = QComboBox()
        self.devices = []
        system = System.local()
        for dev in system.devices:
            if allowed_types is None or dev.product_type in allowed_types:
                display_text = f"{dev.name} - {dev.product_type}"
                self.combo.addItem(display_text, dev)
                self.devices.append(dev)
        
        if not self.devices:
            self.combo.addItem("No matching devices found", None)

        layout.addWidget(QLabel("Choose a device:"))
        layout.addWidget(self.combo)

        # OK/Cancel buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_device(self):
        if self.combo.currentData() is None:
            return None
        return {'name':self.combo.currentData().name, 'model': self.combo.currentData().product_type }

                

# === Recording Worker Thread ===
class RecordingWorker(QThread):
    file_exception = pyqtSignal(str)
    def __init__(self, data_queue, active_flag):
        super().__init__()
        self.data_queue = data_queue
        self.active_flag = active_flag
        self.running = False
        self.file = None
        self.writer = None
        self.active_channels = []

    def start_recording(self, filename):
        try:
            self.file = open(filename, 'w', newline='')
        except (OSError, IOError) as e:
            self.file_exception.emit(f"Error opening file: {e}")
            return
        data_fields = ['timestamp'] + self.active_channels
        self.writer = csv.DictWriter(self.file, fieldnames=data_fields)
        self.writer.writeheader()
        self.running = True
        self.active_flag.set()
        self.start()

    def run(self):
        while self.running:
            while not self.data_queue.empty():
                sample = self.data_queue.get()
                try:
                    self.writer.writerow(sample)
                except (OSError, IOError, ValueError) as e:
                    self.file_exception.emit(f"Error writing to CSV file: {e}")
                    self.stop_recording()
                    return
            time.sleep(0.01)  # Prevent CPU hogging

    def stop_recording(self):
        self.running = False
        self.active_flag.clear()
        self.wait()
        if self.file:
            self.file.close()
            self.file = None

    def update_config(self, config):
        self.stop_recording()
        #update active channels
        self.active_channels = []
        for channel in config['analog'].keys():
            if(config['analog'][channel]['enabled']):
                self.active_channels.append(channel)
        for channel in config['digital'].keys():
            if(config['digital'][channel]['enabled']):
                self.active_channels.append(channel)

# === Config Tab (Placeholder) ===
class ConfigTab(QWidget):
    config_changed = pyqtSignal(dict)
    structure_changed = pyqtSignal(dict)

    def __init__(self, config_data : dict):
        super().__init__()
        self.config_data = config_data

        layout = QVBoxLayout()

        top_group_layout = QVBoxLayout()
        # Current device / sample rate
        top_layout = QHBoxLayout()
        self.current_device_name = QLabel("Selected Device: None Selected")
        self.current_sample = QLabel("Current Sample Rate: None Selected")
        self.current_sample.setAlignment(Qt.AlignRight)
        top_layout.addWidget(self.current_device_name)
        top_layout.addWidget(self.current_sample)
        top_group_layout.addLayout(top_layout)

        #change sample rate
        sample_layout = QHBoxLayout()
        self.sample_rate_input = QLineEdit()
        self.select_sample_rate_button = QPushButton("Set Sample Rate")
        self.select_sample_rate_button.clicked.connect(self.changed_sample_rate)
        sample_rate_unit = QLabel("Hz")
        sample_layout.addWidget(self.select_sample_rate_button)
        sample_layout.addWidget(self.sample_rate_input)
        sample_layout.addWidget(sample_rate_unit)
        top_group_layout.addLayout(sample_layout)

        # Save / Load / Device / sample rate buttons
        self.loading_flag = False
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save Config")
        load_button = QPushButton("Load Config")
        choose_device_button = QPushButton("Select Device")
        save_button.clicked.connect(self.save_config)
        load_button.clicked.connect(self.load_config)
        choose_device_button.clicked.connect(self.select_any_device)
        button_layout.addWidget(save_button)
        button_layout.addWidget(load_button)
        button_layout.addWidget(choose_device_button)
        top_group_layout.addLayout(button_layout)

        # top group
        layout.addLayout(top_group_layout, stretch=0)

        
        # Analog Inputs Group
        analog_group = QGroupBox("Analog Inputs")
        self.analog_layout = QVBoxLayout()
        self.analog_widgets = {}
        

        analog_group.setLayout(self.analog_layout)
        layout.addWidget(analog_group, stretch=1)

        # Digital IO Group
        digital_group = QGroupBox("Digital IO")
        self.digital_layout = QVBoxLayout()
        self.digital_widgets = {}
        
        digital_group.setLayout(self.digital_layout)
        layout.addWidget(digital_group, stretch=1)
        self.setLayout(layout)

    def update_config(self):
        if(self.loading_flag): 
            return
        # Read analog configurations
        for channel_name in self.config_data['analog'].keys():
            self.config_data['analog'][channel_name]['enabled'] = self.analog_widgets[channel_name]['enable_cb'].isChecked()
            self.config_data['analog'][channel_name]['mode'] = self.analog_widgets[channel_name]['mode_cb'].currentText()

        # Read digital configurations
        for channel_name in self.config_data['digital'].keys():
            self.config_data['digital'][channel_name]['enabled'] = self.digital_widgets[channel_name]['enable_cb'].isChecked()
            self.config_data['digital'][channel_name]['mode'] = self.digital_widgets[channel_name]['mode_cb'].currentText()
        
        self.config_changed.emit(self.config_data)

    def save_config(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getSaveFileName(self, "Save Config As", "", "JSON Files (*.json)", options=options)
        if filename:
            try:
                with open(filename, 'w') as f:
                    json.dump(self.config_data, f, indent=4)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save config: {e}")

    def load_config(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getOpenFileName(self, "Load Config", "", "JSON Files (*.json)", options=options)
        if filename:
            try:
                with open(filename, 'r') as f:
                    new_config = json.load(f)
                    device = self.select_device(new_config['device']['model'])
                    if(device):
                        new_config['device']['name'] = device['name']
                        new_config['device']['model'] = device['model']
                        self.config_data = new_config
                        self.update_ui_layout()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load config: {e}")

    def update_ui_layout(self):
        #Analog Widgets
        self.analog_widgets = {}
        clear_layout(self.analog_layout)
        for channel_name in self.config_data['analog'].keys():
            layout = QHBoxLayout()
            channel_widgets = {'enable_cb':QCheckBox(channel_name), 'mode_cb':QComboBox()}
            channel_widgets['mode_cb'].addItems(self.config_data['analog'][channel_name]['modes'])
            channel_widgets['mode_cb'].currentIndexChanged.connect(self.update_config)
            channel_widgets['enable_cb'].stateChanged.connect(self.update_config)
            layout.addWidget(channel_widgets['enable_cb'])
            layout.addWidget(channel_widgets['mode_cb'])
            self.analog_widgets[channel_name] = channel_widgets
            self.analog_layout.addLayout(layout)

        #Digital Widgets
        self.digital_widgets = {}
        clear_layout(self.digital_layout)
        for channel_name in self.config_data['digital'].keys():
            layout = QHBoxLayout()
            channel_widgets = {'enable_cb':QCheckBox(channel_name), 'mode_cb':QComboBox()}
            channel_widgets['mode_cb'].addItems(self.config_data['digital'][channel_name]['modes'])
            channel_widgets['mode_cb'].currentIndexChanged.connect(self.update_config)
            channel_widgets['enable_cb'].stateChanged.connect(self.update_config)
            layout.addWidget(channel_widgets['enable_cb'])
            layout.addWidget(channel_widgets['mode_cb'])
            self.digital_widgets[channel_name] = channel_widgets
            self.digital_layout.addLayout(layout)
        self.structure_changed.emit(self.config_data)
        self.apply_config_to_ui()

    def apply_config_to_ui(self):
        self.loading_flag = True

        #Analog Widgets
        for channel_name in self.config_data['analog'].keys():
            self.analog_widgets[channel_name]['enable_cb'].setChecked(self.config_data['analog'][channel_name]['enabled'])
            self.analog_widgets[channel_name]['mode_cb'].setCurrentText(self.config_data['analog'][channel_name]['mode'])

        #Digital Widgets
        for channel_name in self.config_data['digital'].keys():
            self.digital_widgets[channel_name]['enable_cb'].setChecked(self.config_data['digital'][channel_name]['enabled'])
            self.digital_widgets[channel_name]['mode_cb'].setCurrentText(self.config_data['digital'][channel_name]['mode'])
        self.loading_flag = False

        #Top Widgets
        self.update_device_text()
        self.update_sample_rate_text()

        #Update config for self and others
        self.update_config()


    def get_num_analog_signals(self):
        return 8
    
    def get_num_digital_signals(self):
        return 8
    
    def select_device(self, device_type):
        dialog = DeviceSelectDialog(allowed_types=device_type)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.selected_device()
        return None
        
    def select_any_device(self):
        device = self.select_device(None)
        if(device):
            self.config_data = make_default_config(device['name'])
            self.update_ui_layout()

    def update_device_text(self):
        if(self.config_data['device']['model'] and self.config_data['device']['name']):
            self.current_device_name.setText(f"Selected Device: {self.config_data['device']['name']} ({self.config_data['device']['model']})")
        else:
            self.current_device_name.setText(f"Selected Device: None")

    def update_sample_rate_text(self):
        if(self.config_data['device']['sample_rate']):
            self.current_sample.setText(f"Current Sample Rate: {self.config_data['device']['sample_rate']}Hz")
        else:
            self.current_sample.setText(f"Current Sample Rate: None Selected")

    def changed_sample_rate(self):
        input_val = self.sample_rate_input.text()
        try:
            if not input_val:
                raise Exception("No value")
            value = float(input_val)
            if(value <= 0):
                raise Exception("Sample rate cannot be negative")
            if(value > 1e6):
                raise Exception("Sample rate is too large")
            self.config_data['device']['sample_rate'] = value
            self.apply_config_to_ui()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Invalid sample rate: {e}")

    def reset_config(self):
        if(self.config_data['device']['name']):
            self.config_data = make_default_config(self.config_data['device']['name'])
        else:
            self.config_data = null_config()
        self.update_ui_layout()


        

# === Plots Tab with PyQtGraph ===
class PlotsTab(QWidget):
    def __init__(self, data_queue):
        super().__init__()
        self.data_queue = data_queue

        self.max_points = 500
        self.x_data = []
        self.y_data = {}  # analog channel index -> list of samples
        self.bool_data = {} # digital channel index -> list of samples
        self.curves = {}  # analog channel index -> pg.PlotDataItem
        self.waveforms = {} # digital channel index -> pg.PlotDataItem

        layout = QVBoxLayout()
        self.plot_widget = pg.PlotWidget(title="Live DAQ Analog Data")
        self.plot_widget.setLabel('left', 'Voltage', units='V')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.digital_plot_widget = pg.PlotWidget(title="Live DAQ Digital Data")
        self.digital_plot_widget.setLabel('left', 'Logic Value')
        self.digital_plot_widget.setLabel('bottom', 'Time', units='s')
        layout.addWidget(self.plot_widget)
        layout.addWidget(self.digital_plot_widget)
        self.setLayout(layout)

        self.active_channels = []  # list of analog channel indices
        self.active_digital_channels = [] # list of digital channel indices

        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self.update_plot)
        self.plot_timer.start(20)  # update 20 Hz

    def update_plot(self):
        updated = False
        while not self.data_queue.empty():
            sample = self.data_queue.get()
            self.x_data.append(sample['timestamp'])

            for ch_idx in self.active_channels:
                ch_name = f"AI{ch_idx}"
                if ch_name in sample:
                    self.y_data[ch_idx].append(sample[ch_name])
                else:
                    self.y_data[ch_idx].append(0)

            for i in range(0,len(self.active_digital_channels)):
                ch_idx = self.active_digital_channels[i]
                ch_name = f"DIO{ch_idx}"
                if ch_name in sample:
                    self.bool_data[ch_idx].append(self.binaryPlotValue(i, sample[ch_name]))
                else:
                    self.bool_data[ch_idx].append(self.binaryPlotValue(i, 0))

            updated = True

        if updated:
            if len(self.x_data) > self.max_points:
                self.x_data = self.x_data[-self.max_points:]
                #truncate analog curve data
                for ch_idx in self.active_channels:
                    self.y_data[ch_idx] = self.y_data[ch_idx][-self.max_points:]
                #truncate digital waveform data
                for ch_idx in self.active_digital_channels:
                    self.bool_data[ch_idx] = self.bool_data[ch_idx][-self.max_points:]

            if self.x_data:
                t0 = self.x_data[0]
                x_shifted = [t - t0 for t in self.x_data]
                #update analog curves
                for ch_idx in self.active_channels:
                    self.curves[ch_idx].setData(x_shifted, self.y_data[ch_idx])
                #update digital waveforms
                x_shifted.insert(0,x_shifted[0])
                for ch_idx in self.active_digital_channels:
                    self.waveforms[ch_idx].setData(x_shifted, self.bool_data[ch_idx])
            

    def update_config(self, config):
        # === ANALOG ===
        # Remove curves for analog channels that are no longer active
        for ch_idx in list(self.active_channels):
            if not ch_idx in config['analog'].keys() or not config['analog'][ch_idx]['enabled']:
                self.plot_widget.removeItem(self.curves[ch_idx])
                del self.curves[ch_idx]
                del self.y_data[ch_idx]
                self.active_channels.remove(ch_idx)
            else:
                self.y_data[ch_idx] = []

        # Add curves for newly active analog channels
        for channel in config['analog'].keys():
            if config['analog'][channel]['enabled'] and channel not in self.active_channels:
                pen_color = pg.intColor(len(self.curves))
                self.curves[channel] = self.plot_widget.plot(pen=pen_color, name=channel)
                self.y_data[channel] = []
                self.active_channels.append(channel)

        # === DIGITAL ===
        # Remove previous digital waveforms
        for ch_idx in list(self.active_digital_channels):
            self.digital_plot_widget.removeItem(self.waveforms[ch_idx])
        self.waveforms = {}
        self.bool_data = {}
        self.active_digital_channels = []
            
        # Add curves for newly active digital channels
        for channel in config['digital'].keys(): 
            if config['digital'][channel]['enabled']:
                pen_color = pg.intColor(len(self.waveforms))
                self.waveforms[channel] = self.digital_plot_widget.plot([0, 0], [0], pen=pen_color, stepMode=True, name=channel)
                self.bool_data[channel] = []
                self.active_digital_channels.append(channel)

        # Update digital channel plot 
        y_axis = self.digital_plot_widget.getAxis('left')
        ticks = []
        count = 0
        for channel in self.active_digital_channels:
            ticks.append([count+0.5, channel])
            count = count+1
            
        y_axis.setTicks([ticks])
        self.digital_plot_widget.setYRange(0, len(self.active_digital_channels))

        # === GENERAL ===
        #reset timestamps
        self.x_data = []
    
    def binaryPlotValue(self, index, truthValue):
        position = index + 0.5
        if(truthValue):
            position = position + 1/3.0
        else:
            position = position - 1/3.0
        return position
        
        

# === Recording Tab with Controls ===
class RecordingTab(QWidget):
    start_recording_signal = pyqtSignal(str)
    stop_recording_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        self.status_label = QLabel("Not Recording")
        self.start_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop Recording")
        self.stop_button.setEnabled(False)
        self.filename = None
        self.recording = False

        self.start_button.clicked.connect(self.start_recording)
        self.stop_button.clicked.connect(self.stop_recording)

        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

    def start_recording(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getSaveFileName(self, "Save Recording As", "", "CSV Files (*.csv)", options=options)
        if filename:
            self.status_label.setText(f"Recording...")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.filename = filename
            self.recording = True
            self.start_recording_signal.emit(filename)

    def stop_recording(self):
        if(self.recording):
            QMessageBox.information(self,"Info", f"Recording stoped and saved to: {self.filename}")
        self.recording = False
        self.status_label.setText("Not Recording")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.stop_recording_signal.emit()

# === Start/Stop Tab ===
class ControlTab(QWidget):
    start_daq_signal = pyqtSignal()
    stop_daq_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        self.status_label = QLabel("DAQ Stoped")
        self.start_button = QPushButton("Start DAQ")
        self.stop_button = QPushButton("Stop DAQ")
        self.stop_button.setEnabled(False)

        self.start_button.clicked.connect(self.start_daq)
        self.stop_button.clicked.connect(self.stop_daq)

        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

    def start_daq(self):
        self.status_label.setText("DAQ Running...")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.start_daq_signal.emit()

    def stop_daq(self):
        self.status_label.setText("DAQ Stoped")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.stop_daq_signal.emit()

# === Start/Stop Tab ===
class OutputTab(QWidget):
    update_output_signal = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self.layout = QGridLayout()
        self.status_label = QLabel("DAQ Stoped")
        self.buttons = {}
        self.setLayout(self.layout)

    def button_callback(self, button):
        if(self.buttons[button].isChecked()):
            self.update_output_signal.emit(button, 1)
        else:
            self.update_output_signal.emit(button, 0)

    def update_layout(self, config):
        clear_layout(self.layout)
        self.buttons = {}
        i = 0
        for channel in config['digital'].keys():
            self.buttons[channel] = QPushButton(channel)
            self.buttons[channel].setEnabled(False)
            self.buttons[channel].setCheckable(True)
            self.buttons[channel].clicked.connect(lambda _, c = channel: self.button_callback(c))
            self.layout.addWidget(self.buttons[channel], i // 2, i % 2)
            i = i+1


    def update_config(self, config):
        for channel in config['digital'].keys():
            self.buttons[channel].setChecked(False)
            if(config['digital'][channel]['enabled'] and config['digital'][channel]['mode'] == 'Output'):
                self.buttons[channel].setEnabled(True)
            else:
                self.buttons[channel].setEnabled(False)

# === Main Application ===
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NI DAQ Control System")
        self.resize(800, 600)

        #shared data
        self.plot_queue = queue.Queue(maxsize=1000)
        self.record_queue = queue.Queue(maxsize=1000)
        self.recording_flag = threading.Event()
        self.config_data = null_config()

        # DAQ Thread
        self.daq_worker = DAQWorker(self.plot_queue, self.record_queue, self.recording_flag)
        self.daq_worker.configuration_exception.connect(self.handle_config_exception)

        # Layout
        layout = QHBoxLayout()
        main_layout = QVBoxLayout()
        upper_layout = QHBoxLayout()

        # Control Section
        self.running_group = QGroupBox("DAQ Control")
        running_layout = QVBoxLayout()
        self.control_tab = ControlTab()
        self.control_tab.start_daq_signal.connect(self.start_daq)
        self.control_tab.stop_daq_signal.connect(self.stop_daq)
        running_layout.addWidget(self.control_tab)
        self.running_group.setLayout(running_layout)

        #Recording Section
        self.recording_group = QGroupBox("Recording")
        recording_layout = QVBoxLayout()
        self.recording_tab = RecordingTab()
        recording_layout.addWidget(self.recording_tab)
        self.recording_group.setLayout(recording_layout)

        #Output Section
        self.output_group = QGroupBox("DAQ Outputs")
        output_layout = QVBoxLayout()
        self.output_tab = OutputTab()
        self.output_tab.update_output_signal.connect(self.input_update)
        output_layout.addWidget(self.output_tab)
        self.output_group.setLayout(output_layout)

        #Organize widgets
        upper_layout.addWidget(self.running_group)
        upper_layout.addWidget(self.recording_group)
        main_layout.addLayout(upper_layout)
        main_layout.addWidget(self.output_group)
        main_layout.setStretch(0,0)
        main_layout.setStretch(1,1)
        layout.addLayout(main_layout)

        # Tabs
        tabs = QTabWidget()
        self.config_tab = ConfigTab(self.config_data)
        tabs.addTab(self.config_tab, "Configuration")
        self.plots_tab = PlotsTab(self.plot_queue)
        tabs.addTab(self.plots_tab, "Plots")
        layout.addWidget(tabs)

        #Establish GUI
        self.setLayout(layout)

        # Recording Thread
        self.recording_worker = RecordingWorker(self.record_queue, self.recording_flag)
        
        # Connect Recording Signals
        self.recording_worker.file_exception.connect(self.file_exception)
        self.recording_tab.start_recording_signal.connect(self.start_recording)
        self.recording_tab.stop_recording_signal.connect(self.stop_recording)

        # Connect Configuration Signals
        self.config_tab.config_changed.connect(self.handle_config_update)
        self.config_tab.structure_changed.connect(self.handle_config_structure_update)

        

    @pyqtSlot(str)
    def start_recording(self, filename):
        self.recording_worker.start_recording(filename)

    @pyqtSlot()
    def stop_recording(self):
        self.recording_worker.stop_recording()

    @pyqtSlot(str)
    def file_exception(self, message):
        QMessageBox.critical(self,"Error", message)

    @pyqtSlot(str, int)
    def input_update(self, button, value):
        print('update')
        #self.daq_worker.user_input(button, value)

    def stop_daq(self):
        self.daq_worker.stop()
        self.recording_tab.stop_recording()

    def start_daq(self):
        #self.handle_config_update(self.config_data)
        self.daq_worker.start()

    @pyqtSlot(dict)
    def handle_config_update(self, config):
        self.control_tab.stop_daq()
        self.config_data = config
        self.recording_worker.update_config(config)
        self.recording_tab.stop_recording()
        self.daq_worker.update_config(config)
        self.plots_tab.update_config(config)
        self.output_tab.update_config(config)

    @pyqtSlot(dict)
    def handle_config_structure_update(self, config):
        self.output_tab.update_layout(config)

    @pyqtSlot(str)
    def handle_config_exception(self, message : str):
        self.config_tab.reset_config()
        QMessageBox.critical(self,"Error", message)

# === Run App ===
app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec_())