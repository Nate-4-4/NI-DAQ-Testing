import sys
import time
import random
import queue
import csv
from PyQt5.QtWidgets import QApplication, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QPushButton, QFileDialog, QMessageBox, QGroupBox, QGridLayout
from PyQt5.QtCore import QThread, QTimer, pyqtSignal, pyqtSlot
import pyqtgraph as pg
import threading
import json
import math

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
                'AI0': random.uniform(-5, 5),
                'AI1': random.uniform(-5, 5),
                'AI2': random.uniform(-5, 5),
                'AI3': random.uniform(-5, 5),
                'AI4': random.uniform(-5, 5),
                'AI5': random.uniform(-5, 5),
                'AI6': random.uniform(-5, 5),
                'AI7': random.uniform(-5, 5),
                'DIO0': math.floor(random.uniform(0, 1) + 0.5),
                'DIO1': math.floor(random.uniform(0, 1) + 0.5),
                'DIO2': math.floor(random.uniform(0, 1) + 0.5),
                'DIO3': math.floor(random.uniform(0, 1) + 0.5),
                'DIO4': math.floor(random.uniform(0, 1) + 0.5),
                'DIO5': math.floor(random.uniform(0, 1) + 0.5),
                'DIO6': math.floor(random.uniform(0, 1) + 0.5),
                'DIO7': math.floor(random.uniform(0, 1) + 0.5),
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
        for i in range(8):
            if(config['analog'][i]['enabled']):
                self.active_channels.append(f"AI{i}")
        for i in range(8):
            if(config['digital'][i]['enabled'] and config['digital'][i]['mode'] == 'Input'):
                self.active_channels.append(f"DIO{i}")
        self.user_inputs = {}
        for i in range(8):
            self.user_inputs[i] = 0
            if(config['digital'][i]['enabled'] and config['digital'][i]['mode'] == 'Output'):
                self.user_input_channels.append(f"DIO{i}")

    def user_input(self, channel, value):
        self.user_inputs[channel] = value  

                

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
        for i in range(8):
            if(config['analog'][i]['enabled']):
                self.active_channels.append(f"AI{i}")
        for i in range(8):
            if(config['digital'][i]['enabled']):
                self.active_channels.append(f"DIO{i}")

# === Config Tab (Placeholder) ===
class ConfigTab(QWidget):
    config_changed = pyqtSignal(dict)

    def __init__(self, config_data):
        super().__init__()

        self.config_data = config_data

        layout = QVBoxLayout()

        # Save / Load Buttons
        self.loading_flag = False
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save Config")
        load_button = QPushButton("Load Config")
        save_button.clicked.connect(self.save_config)
        load_button.clicked.connect(self.load_config)
        button_layout.addWidget(save_button)
        button_layout.addWidget(load_button)
        layout.addLayout(button_layout)

        # Analog Inputs Group
        analog_group = QGroupBox("Analog Inputs (AI0 - AI7)")
        analog_layout = QGridLayout()
        self.analog_widgets = []
        for i in range(8):
            enable_cb = QCheckBox(f"AI{i}")
            mode_cb = QComboBox()
            if(i<4):
                mode_cb.addItems(['Ground', 'Reference']) #AI0-3 can use reference or ground mode
            else:
                mode_cb.addItem('Ground') #AI4-7 can only use ground mode
                mode_cb.setEnabled(False)
            analog_layout.addWidget(enable_cb, i, 0)
            analog_layout.addWidget(mode_cb, i, 1)
            self.analog_widgets.append((enable_cb, mode_cb))

            enable_cb.stateChanged.connect(self.update_config)
            if(i<4):
                mode_cb.currentIndexChanged.connect(self.update_config) #dropdowns for AI4-7 cannot be changed

        analog_group.setLayout(analog_layout)
        layout.addWidget(analog_group)

        # Digital IO Group
        digital_group = QGroupBox("Digital IO (DIO0 - DIO7)")
        digital_layout = QGridLayout()
        self.digital_widgets = []
        for i in range(8):
            enable_cb = QCheckBox(f"DIO{i}")
            mode_cb = QComboBox()
            mode_cb.addItems(['Input', 'Output'])
            digital_layout.addWidget(enable_cb, i, 0)
            digital_layout.addWidget(mode_cb, i, 1)
            self.digital_widgets.append((enable_cb, mode_cb))

            enable_cb.stateChanged.connect(self.update_config)
            mode_cb.currentIndexChanged.connect(self.update_config)

        digital_group.setLayout(digital_layout)
        layout.addWidget(digital_group)

        

        self.setLayout(layout)

    def update_config(self):
        if(self.loading_flag): 
            return
        # Read analog configurations
        for i, (enable_cb, mode_cb) in enumerate(self.analog_widgets):
            self.config_data['analog'][i]['enabled'] = enable_cb.isChecked()
            self.config_data['analog'][i]['mode'] = mode_cb.currentText()

        # Handle AI(n+4) disable logic
        for i in range(4):
            if self.analog_widgets[i][1].currentText() == 'Reference':
                self.analog_widgets[i+4][0].setChecked(False)
                self.analog_widgets[i+4][0].setEnabled(False)
            else:
                self.analog_widgets[i+4][0].setEnabled(True)

        # Read digital configurations
        for i, (enable_cb, mode_cb) in enumerate(self.digital_widgets):
            self.config_data['digital'][i]['enabled'] = enable_cb.isChecked()
            self.config_data['digital'][i]['mode'] = mode_cb.currentText()

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
                    self.config_data = json.load(f)
                self.apply_config_to_ui()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load config: {e}")

    def apply_config_to_ui(self):
        self.loading_flag = True
        for i, (enable_cb, mode_cb) in enumerate(self.analog_widgets):
            enable_cb.setChecked(self.config_data['analog'][i]['enabled'])
            mode_cb.setCurrentText(self.config_data['analog'][i]['mode'])

        for i, (enable_cb, mode_cb) in enumerate(self.digital_widgets):
            enable_cb.setChecked(self.config_data['digital'][i]['enabled'])
            mode_cb.setCurrentText(self.config_data['digital'][i]['mode'])
        self.loading_flag = False
        self.update_config()

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
        for ch_idx, settings in enumerate(config['analog']):
            if settings['enabled'] and ch_idx not in self.active_channels:
                pen_color = pg.intColor(len(self.curves))
                self.curves[ch_idx] = self.plot_widget.plot(pen=pen_color, name=f"AI{ch_idx}")
                self.y_data[ch_idx] = []
                self.active_channels.append(ch_idx)

        # === DIGITAL ===
        # Remove previous digital waveforms
        for ch_idx in list(self.active_digital_channels):
            self.digital_plot_widget.removeItem(self.waveforms[ch_idx])
        self.waveforms = {}
        self.bool_data = {}
        self.active_digital_channels = []
            
        # Add curves for newly active digital channels
        for ch_idx, settings in enumerate(config['digital']): 
            if settings['enabled']:
                pen_color = pg.intColor(len(self.waveforms))
                self.waveforms[ch_idx] = self.digital_plot_widget.plot([0, 0], [0], pen=pen_color, stepMode=True, name=f"DIO{ch_idx}")
                self.bool_data[ch_idx] = []
                self.active_digital_channels.append(ch_idx)

        # Update digital channel plot 
        y_axis = self.digital_plot_widget.getAxis('left')
        ticks = []
        for i in range(0,len(self.active_digital_channels)):
            if(config['digital'][self.active_digital_channels[i]]['mode'] == "Input"):
                ticks.append((i+0.5, f"DI{self.active_digital_channels[i]}"))
            else:
                ticks.append((i+0.5, f"DO{self.active_digital_channels[i]}"))
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
           button.clicked.connect(lambda checked, i = i: self.button_callback(i))
           layout.addWidget(button, i % 4, i // 4)

        self.setLayout(layout)

    def button_callback(self, button):
        if(self.buttons[button].isChecked()):
            self.update_output_signal.emit(button, 1)
        else:
            self.update_output_signal.emit(button, 0)

    def update_config(self, config):
        for i in range(8):
            self.buttons[i].setChecked(False)
            if(config['digital'][i]['enabled'] and config['digital'][i]['mode'] == 'Output'):
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
            'analog': [{'enabled': False, 'mode': 'Ground'} for _ in range(8)],
            'digital': [{'enabled': False, 'mode': 'Input'} for _ in range(8)]
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
        self.output_tab.update_config(config)

# === Run App ===
app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec_())