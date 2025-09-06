from nidaqmx.system import System

system = System.local()

print("Connected DAQ devices:\n")

for dev in system.devices:
    print(f"Device name: {dev.name}")
    print(f"  Product type: {dev.product_type}")
    
    # Query available channels
    ai_chans = list(dev.ai_physical_chans)
    ao_chans = list(dev.ao_physical_chans)
    di_chans = list(dev.di_ports)      # digital I/O is usually port-based
    do_chans = list(dev.do_ports)

    print(f"  Analog Input Channels:  {len(ai_chans)}")
    print(f"  Analog Output Channels: {len(ao_chans)}")
    print(f"  Digital Input Ports:    {len(di_chans)}")
    print(f"  Digital Output Ports:   {len(do_chans)}")
    print("-" * 40)

    for port in dev.di_ports:
        print(f"{port.name} has {port.di_port_width} lines")