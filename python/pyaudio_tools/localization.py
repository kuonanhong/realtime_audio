__author__ = 'adamjmiller'
import pyaudio
import time
import numpy as np
import threading
import math
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from pa_tools.audiohelper import AudioHelper
from pa_tools.audiobuffer import AudioBuffer
from pa_tools.stftmanager import StftManager
from pa_tools.audiolocalizer import AudioLocalizer
from pa_tools.distributionlocalizer import DistributionLocalizer


# Setup constants
SAMPLE_TYPE = pyaudio.paFloat32
DATA_TYPE = np.float32
SAMPLE_SIZE = pyaudio.get_sample_size(SAMPLE_TYPE)
SAMPLE_RATE = 16000
FRAMES_PER_BUF = 1024  # Do not go below 64
FFT_LENGTH = FRAMES_PER_BUF
WINDOW_LENGTH = FFT_LENGTH
HOP_LENGTH = WINDOW_LENGTH / 2
NUM_CHANNELS_IN = 2
NUM_CHANNELS_OUT = 2
N_THETA = 20
N_PHI = N_THETA / 2
PLOT_CARTES = False
PLOT_POLAR = False
EXTERNAL_PLOT = False
PLAY_AUDIO = True
TIMEOUT = 1


# Setup mics
R = 0.0375
H = 0.07
mic_layout = np.array([[0, 0, H],
     [R, 0, 0],
     [R*math.cos(math.pi/3), R*math.sin(math.pi/3), 0],
     [-R*math.cos(math.pi/3), R*math.sin(math.pi/3), 0],
     [-R, 0, 0],
     [-R*math.cos(math.pi/3), -R*math.sin(math.pi/3), 0],
     [R*math.cos(math.pi/3), -R*math.sin(math.pi/3), 0]])
# Track whether we have quit or not
done = False

# Events for signaling new data is available
audio_produced_event = threading.Event()
data_produced_event = threading.Event()

# Setup data buffers - use 4 * buffer length in case data get's backed up
# at any point, so it will not be lost
in_buf = AudioBuffer(length=4 * FRAMES_PER_BUF, n_channels=NUM_CHANNELS_IN)
out_buf = AudioBuffer(length=4 * FRAMES_PER_BUF, n_channels=NUM_CHANNELS_OUT)


def read_in_data(in_data, frame_count, time_info, status_flags):
    if done:  # Must do this or calls to stop_stream may not succeed
        return None, pyaudio.paComplete
    write_num = in_buf.get_available_write()
    if write_num > frame_count:
        write_num = frame_count
    in_buf.write_bytes(in_data[:(write_num * SAMPLE_SIZE * NUM_CHANNELS_IN)])
    in_buf.notify_of_audio()
    return None, pyaudio.paContinue


def write_out_data(in_data, frame_count, time_info, status_flags):
    if done:  # Must do this or calls to stop_stream may not succeed
        return None, pyaudio.paComplete
    if out_buf.get_available_read() >= frame_count:
        return out_buf.read_bytes(frame_count), pyaudio.paContinue
    else:  # Return empty data (returning None will trigger paComplete)
        return '\x00' * frame_count * SAMPLE_SIZE * NUM_CHANNELS_OUT, pyaudio.paContinue


def process_dfts(dfts):
    for (reals, imags) in dfts:
        for real in reals:
            process_dft_buf(real)
        for imag in imags:
            process_dft_buf(imag)


def process_dft_buf(buf):
    # Low pass filter:
    for i in range(len(buf)):
        if i > FFT_LENGTH / 16:
            buf[i] = 0
    pass


def check_for_quit():
    global done
    while True:
        read_in = raw_input()
        if read_in == "q":
            print "User has chosen to quit."
            done = True
            break


def check_new_data_event():
    global data_produced_event
    global done
    while True:
        result = audio_produced_event.wait(TIMEOUT)
        audio_produced_event.clear()
        if not result:
            break
        available = min(in_buf.get_available_read(), out_buf.get_available_write())
        if available >= WINDOW_LENGTH:
            print "set"
            data_produced_event.set()
    print "Exiting event updater thread"


def print_dfts(dfts):
    print "Printing DFTS:"
    print dfts
    sample_len = 12
    for k in range(len(dfts)):
        print "Channel %d" %k
        reals = dfts[k][0]
        imags = dfts[k][1]
        for i in range(len(reals)):
            print "Reals %d:" %i
            out_str = ""
            for j in range(sample_len):
                out_str += "%f\t" %reals[i][j]
            print out_str
        for i in range(len(imags)):
            print "Imags %d:" %i
            out_str = ""
            for j in range(sample_len):
                out_str += "%f\t" %reals[i][j]
            print out_str


def localize():
    # Setup pyaudio instances
    pa = pyaudio.PyAudio()
    helper = AudioHelper(pa)
    localizer = DistributionLocalizer(mic_layout=mic_layout,
                                      dft_len=FFT_LENGTH,
                                      sample_rate=SAMPLE_RATE,
                                      n_theta=N_THETA,
                                      n_phi=N_PHI)

    # Setup STFT object
    stft = StftManager(dft_length=FFT_LENGTH,
                       window_length=WINDOW_LENGTH,
                       hop_length=HOP_LENGTH,
                       use_window_fcn=True,
                       n_channels=NUM_CHANNELS_IN,
                       dtype=DATA_TYPE)

    # Setup devices
    in_device = helper.get_input_device_from_user()
    if PLAY_AUDIO:
        out_device = helper.get_output_device_from_user()
    else:
        out_device = helper.get_default_output_device_info()

    # Setup streams
    in_stream = pa.open(rate=SAMPLE_RATE,
                        channels=NUM_CHANNELS_IN,
                        format=SAMPLE_TYPE,
                        frames_per_buffer=FRAMES_PER_BUF,
                        input=True,
                        input_device_index=int(in_device['index']),
                        stream_callback=read_in_data)
    out_stream = pa.open(rate=SAMPLE_RATE,
                             channels=NUM_CHANNELS_OUT,
                             format=SAMPLE_TYPE,
                             output=True,
                             frames_per_buffer=FRAMES_PER_BUF,
                             output_device_index=int(out_device['index']),
                             stream_callback=write_out_data)

    # Start recording/playing back
    in_stream.start_stream()
    out_stream.start_stream()

    # Start thread to check for user quit
    quit_thread = threading.Thread(target=check_for_quit)
    quit_thread.start()

    # Plotting
    if PLOT_CARTES:
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        plt.show(block=False)
        scat = []
    if PLOT_POLAR:
        fig = plt.figure()
        ax = fig.add_axes([.1, .1, .8, .8], projection='polar')
        plt.show(block=False)

    data1 = np.zeros(WINDOW_LENGTH, dtype=DATA_TYPE)
    count = 0
    print "Size: " + str(FFT_LENGTH)
    # Track scaling magnitudes for plot
    plot_max = -np.inf
    plot_min = np.inf
    scatter_made = False  # Only setup scatter handle once, then update colors only
    if EXTERNAL_PLOT:
        fig = plt.figure()
        ax = fig.add_subplot(111)
        plt.show(block=False)
    try:
        global done
        while in_stream.is_active() or out_stream.is_active():
            data_available = in_buf.wait_for_read(WINDOW_LENGTH, TIMEOUT)
            if data_available:
                # Get data from the circular buffer
                data = in_buf.read_samples(WINDOW_LENGTH)
                # Perform an stft
                stft.performStft(data)
                # Process dfts from windowed segments of input
                dfts = stft.getDFTs()
                #d = localizer.get_3d_distribution(dfts)
                d = localizer.get_3d_real_distribution(dfts)
                #d[3, :] -= np.min(d[3, :])
                ind = np.argmax(d[3, :])
                u = 1.5 * d[0:3, ind]  # Direction

                # Take car eof plotting
                if count % 1 == 0:
                    if PLOT_CARTES:
                        plt.cla()
                        ax.scatter(d[0, :], d[1, :], d[2, :], s=30, c=d[3, :])
                        ax.plot([0, u[0]], [0, u[1]], [0, u[2]], c='blue')
                        ax.set_xlim(-1, 1)
                        ax.set_ylim(-1, 1)
                        ax.set_zlim(0, 1)
                        #ax.view_init(azim=-90, elev=90)
                        plt.draw()
                    if PLOT_POLAR:
                        plt.cla()
                        spher = localizer.get_spher_coords()
                        d = localizer.to_spher_grid(d[3, :])
                        pol = localizer.to_spher_grid(spher[2, :])
                        weight = 1. - .3 * np.sin(2 * pol)  # Used to pull visualization off edges
                        r = np.sin(pol) * weight
                        theta = localizer.to_spher_grid(spher[1, :])
                        ax.pcolor(theta, r, d, cmap='gist_heat')#, vmin=0, vmax=4)
                        ax.set_rmax(1)
                        #if np.max(d[3, :]) > plot_max:
                        #    plot_max = np.max(d[3, :])
                        #if np.min(d[3, :]) < plot_min:
                        #    plot_min = np.min(d[3, :])
                        #print "plot_max: %f, plot_min: %f" % (plot_max, plot_min)
                        #print "current_max: %f, current_min: %f" % (np.max(d[3, :]), np.min(d[3, :]))
                        plt.draw()
                count += 1

                # Get the istft of the processed data
                if PLAY_AUDIO:
                    new_data = stft.performIStft()
                    new_data = out_buf.reduce_channels(new_data, NUM_CHANNELS_IN, NUM_CHANNELS_OUT)
                    # Write out the new, altered data
                    if out_buf.get_available_write() >= WINDOW_LENGTH:
                        out_buf.write_samples(new_data)
            #time.sleep(.05)
    except KeyboardInterrupt:
        print "Program interrupted"
        done = True


    print "Cleaning up"
    in_stream.stop_stream()
    in_stream.close()
    out_stream.stop_stream()
    out_stream.close()
    pa.terminate()
    print "Done"

if __name__ == '__main__':
    localize()
