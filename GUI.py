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

# === DAQ Worker Thread (Dummy Data Generator) ===
class DAQWorker(QThread):

    def __init__(self, plot_queue, record_queue, record_flag, sample_rate_hz=100):
        super().__init__()
        self.plot_queue = plot_queue
        self.record_queue = record_queue
        self.record_flag = record_flag
        self.sample_interval = 1.0 / sample_rate_hz
        self.active_channels = []
        self.user_input_channels = []
        self.user_inputs = [0 for _ in range(0,8)]
        self.running = False
        self.start_time = 0

    def run(self):
        self.running = True
        self.start_time = time.time()
        while self.running:
            timestamp = time.time() - self.start_time
            # Fake data for now
            dummy_data = {
                'A0': random.uniform(-5, 5),
                'A1': random.uniform(-5, 5),
                'A2': random.uniform(-5, 5),
                'A3': random.uniform(-5, 5),
                'A4': random.uniform(-5, 5),
                'A5': random.uniform(-5, 5),
                'A6': random.uniform(-5, 5),
                'A7': random.uniform(-5, 5),
                'D0.0': math.floor(random.uniform(0, 1) + 0.5),
                'D0.1': math.floor(random.uniform(0, 1) + 0.5),
                'D0.2': math.floor(random.uniform(0, 1) + 0.5),
                'D0.3': math.floor(random.uniform(0, 1) + 0.5),
                'D0.4': math.floor(random.uniform(0, 1) + 0.5),
                'D0.5': math.floor(random.uniform(0, 1) + 0.5),
                'D0.6': math.floor(random.uniform(0, 1) + 0.5),
                'D0.7': math.floor(random.uniform(0, 1) + 0.5),
            }
            data = {
                'timestamp': timestamp,
            }
            for channel in list(self.active_channels):
                data[channel] = dummy_data[channel]
            for i in range(0,8):
                if(f"DIO{i}" in self.user_input_channels):
                    data[f"DIO{i}"] = self.user_inputs[i]
            try:
                self.plot_queue.put_nowait(data)
            except queue.Full:
                pass
            if(self.record_flag.is_set()):
                try:
                    self.record_queue.put_nowait(data)
                except queue.Full:
                    pass
            time.sleep(self.sample_interval)

    def stop(self):
        self.running = False
        self.wait()

    def update_config(self, config):
        self.active_channels = []
        for channel in config['analog'].keys():
            if(config['analog'][channel]['enabled']):
                self.active_channels.append(channel)
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

    def __init__(self, config_data):
        super().__init__()
        self.config_data = config_data

        layout = QVBoxLayout()

        top_group_layout = QVBoxLayout()
        # Current device / sample rate
        top_layout = QHBoxLayout()
        self.current_device_name = QLabel("Selected Device - None Selected")
        self.current_sample = QLabel("Sample Rate - None Selected")
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
                        self.validate_config(new_config)
                        self.config_data = new_config
                        self.update_ui_layout()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load config: {e}")

    def update_ui_layout(self):
        #Analog Widgets
        self.analog_widgets = {}
        ConfigTab.clear_layout(self.analog_layout)
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
        ConfigTab.clear_layout(self.digital_layout)
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
        self.config_data['device']['name'] = device['name']
        self.config_data['device']['model'] = device['model']
        self.apply_config_to_ui()

    def update_device_text(self):
        if(self.config_data['device']['model'] and self.config_data['device']['name']):
            self.current_device_name.setText(f"Selected Device - {self.config_data['device']['name']} ({self.config_data['device']['model']})")
        else:
            self.current_device_name.setText(f"Selected Device - None")

    def update_sample_rate_text(self):
        if(self.config_data['device']['sample_rate']):
            self.current_sample.setText(f"Sample Rate - {self.config_data['device']['sample_rate']}Hz")
        else:
            self.current_sample.setText(f"Sample Rate - None")

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

    def query_num_analog_channels(self, name):
        system = System.local()
        dev = system.devices[name]
        return list(dev.ai_physical_chans)

    def query_num_digital_channels(self, name):
        system = System.local()
        dev = system.devices[name]
        return list(dev.ai_physical_chans)

    def validate_config(self, config):
        pass

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
                    ConfigTab.clear_layout(sub_layout)

        

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
            if not config['analog'][ch_idx]['enabled']:
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
    update_output_signal = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        layout = QGridLayout()
        self.status_label = QLabel("DAQ Stoped")
        self.buttons = [QPushButton(f"DO{i}") for i in range(0,8)]
        for i in range(0,len(self.buttons)):
           button = self.buttons[i]
           button.setEnabled(False)
           button.setCheckable(True)
           button.clicked.connect(lambda _, i = i: self.button_callback(i))
           layout.addWidget(button, i % 4, i // 4)

        self.setLayout(layout)

    def button_callback(self, button):
        if(self.buttons[button].isChecked()):
            self.update_output_signal.emit(button, 1)
        else:
            self.update_output_signal.emit(button, 0)

    def update_config(self, config):
        for i in range(config['digital']['quantity']):
            self.buttons[i].setChecked(False)
            if(config['digital']['settings'][i]['enabled'] and config['digital']['settings'][i]['mode'] == 'Output'):
                self.buttons[i].setEnabled(True)
            else:
                self.buttons[i].setEnabled(False)

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
        self.config_data = {
            'device': {
                'model': None, 
                'name': None, 
                'sample_rate': None
                },
            'analog': {},
            'digital': {}
        }

        # DAQ Thread
        self.daq_worker = DAQWorker(self.plot_queue, self.record_queue, self.recording_flag, sample_rate_hz=50)
        self.daq_worker.start()

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

        #stop DAQ
        self.stop_daq()

    @pyqtSlot(str)
    def start_recording(self, filename):
        self.recording_worker.start_recording(filename)

    @pyqtSlot()
    def stop_recording(self):
        self.recording_worker.stop_recording()

    @pyqtSlot(str)
    def file_exception(self, message):
        QMessageBox.critical(self,"Error", message)

    @pyqtSlot(int, int)
    def input_update(self, button, value):
        self.daq_worker.user_input(button, value)

    def stop_daq(self):
        self.daq_worker.stop()
        self.recording_tab.stop_recording()

    def start_daq(self):
        self.handle_config_update(self.config_data)
        self.daq_worker.start()

    @pyqtSlot(dict)
    def handle_config_update(self, config):
        self.config_data = config
        self.recording_worker.update_config(config)
        self.recording_tab.stop_recording()
        self.daq_worker.update_config(config)
        self.plots_tab.update_config(config)
        #self.output_tab.update_config(config)

# === Run App ===
app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec_())