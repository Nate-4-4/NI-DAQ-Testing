import numpy as np
import matplotlib.pyplot as plt

# Number of signals and length of timeline
num_signals = 4
length = 100

# Create time axis with one extra point for step plotting
t = np.arange(length + 1)

# Generate some fake digital data
# Values are 0 or 1, with random toggles
signals = []
for _ in range(num_signals):
    data = np.random.randint(0, 2, size=length)
    signals.append(np.append(data, data[-1]))  # extend last value for step plotting

# Plot each signal stacked vertically
fig, ax = plt.subplots(figsize=(8, 4))
offset = 0
for i, sig in enumerate(signals):
    ax.step(t, sig + offset, where='post', label=f"Signal {i}")
    offset += 2  # vertical spacing between signals

# Formatting
ax.set_xlabel("Time")
ax.set_yticks(np.arange(0, num_signals * 2, 2))
ax.set_yticklabels([f"Signal {i}" for i in range(num_signals)])
ax.set_ylim(-1, num_signals * 2)
ax.grid(True, which='both', axis='x', linestyle='--', alpha=0.5)
ax.legend(loc='upper right')

plt.tight_layout()
plt.show()

'''
import sys
import numpy as np
from PyQt5.QtWidgets import QApplication
import pyqtgraph as pg


def make_digital_waveform(length, num_signals):
    """Generate synthetic digital signal data."""
    t = np.arange(length+1)
    signals = []
    for i in range(num_signals):
        # Random toggles
        changes = np.random.choice([0, 1], size=length)
        signal = np.zeros(length)
        val = 0
        for j in range(length):
            if changes[j] and np.random.rand() < 0.1:
                val = 1 - val
            signal[j] = val
        signals.append(signal)
    return t, signals


class DigitalTimingPlot(pg.GraphicsLayoutWidget):
    def __init__(self, num_signals=4, length=200):
        super().__init__()
        self.setWindowTitle("Digital Timing Diagram Example")
        self.plot_item = self.addPlot()
        self.plot_item.showGrid(x=True, y=True)

        t, signals = make_digital_waveform(length, num_signals)

        # Offset each signal so they don't overlap
        for i, sig in enumerate(signals):
            offset = i * 1.5  # vertical separation
            y = sig + offset
            # Step plot: draw vertical edges
            self.plot_item.plot(t, y, stepMode=True, fillLevel=None, pen=pg.mkPen(width=2))

        # Adjust y-axis to fit signals nicely
        self.plot_item.setYRange(-1, num_signals * 1.5)
        self.plot_item.setLabel('left', 'Signals')
        self.plot_item.setLabel('bottom', 'Time')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = DigitalTimingPlot()
    win.show()
    sys.exit(app.exec_())
'''