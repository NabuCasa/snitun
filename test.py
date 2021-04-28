from multiprocessing import Process, Manager
import socket
from time import sleep

manager = Manager()
# Store connected sockets
sockets = manager.dict()


def ping_addr(addr=None, port=None, timeout=None):
    """
    Create a socket and try to establish a connection to a specific address. If a connection is established, append
    the socket to the sockets dictionary.
    :param addr: The address.
    :param port: The port number.
    :param timeout: How many seconds to wait until its decided that the connection has been refused.
    :return: None
    """
    global sockets
    # Setup the client socket
    csocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    csocket.settimeout(timeout)
    # Try to connect
    try:
        csocket.connect((addr, port))
        print('connected to {}:{}'.format(addr, port))
        # This works
        #sockets.update({addr: 0})
        # This doesnt work
        sockets.update({addr: csocket})
    except socket.error:
        pass


for i in range(50):
    proc = Process(target=ping_addr, kwargs={'addr': '8.8.8.8', 'port': 53, 'timeout': 0.5})
    proc.start()
    print(len(sockets))
    sleep(1)

sleep(10)
print(len(sockets))
