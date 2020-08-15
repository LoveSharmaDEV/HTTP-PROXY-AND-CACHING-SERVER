import _thread
import socket
import os
import datetime
import time
import json

MAX_CONN = 10
RECV_SIZE = 4096
CACHE_DIR = "./cache"
MAX_CACHE_RECORDS = 3
CACHE_THRESHOLD = 3
PROXY_PORT = 20000

if not os.path.isdir(CACHE_DIR):
    os.makedirs(CACHE_DIR)
for file in os.listdir(CACHE_DIR):
    os.remove(CACHE_DIR + "/" + file)
    

memory = {}

'''
This fuction deals with keeping track of number of times the resource has been requested.
'''
def Cache_Memory(file_requested, client_addr):
    file_requested = file_requested.replace("/", "__")
    if not file_requested in memory:
        memory[file_requested] = []
    dt = time.strptime(time.ctime(), "%a %b %d %H:%M:%S %Y")
    memory[file_requested].append({"request_time": dt,"client": json.dumps(client_addr),})
    
'''
This function deals with setting up the caching policy used.
Caching Policy:
    Every resource that has been requested for than two times and along with that it has been requested
    more than two times within the frame of ten minutes from current time, It would be cached. Else if 
    a resource has not been requested for more than last 10 min, it would not be cached.
'''    
def Cache_Decision(file_requested):
    try:
        file_request_list = memory[file_requested.replace("/", "__")]
        if len(file_request_list) < CACHE_THRESHOLD: 
            return False
        last_resource_request = file_request_list[len(file_request_list)-CACHE_THRESHOLD]["request_time"]
        if datetime.datetime.fromtimestamp(time.mktime(last_resource_request)) + datetime.timedelta(minutes=10) >= datetime.datetime.now():
            return True
        else:
            return False
    except Exception as e:
        print(e)
        return False

'''
This function deals checking if the current resource has been already cached or not
'''
def Get_Current_Cache_Info(file_requested):

    if file_requested.startswith("/"):
        file_requested = file_requested.replace("/", "", 1)

    cache_path = CACHE_DIR + "/" + file_requested.replace("/", "__")

    if os.path.isfile(cache_path):
        last_mtime = time.strptime(time.ctime(os.path.getmtime(cache_path)), "%a %b %d %H:%M:%S %Y")
        return cache_path, last_mtime
    else:
        return cache_path, None
    
'''
This fuction basically adds 3 more components in our detail dictionary
1. request_info["cache_yes_no"]: Tells whether to cache or not
2. request_info["cache_path"]: Its the path to cached file
3. request_info["last_mtime"]: File last modified
'''
def get_cache_request_info(client_addr, request_info):
    Cache_Memory(request_info["total_url"], client_addr)
    cache_yes_no = Cache_Decision(request_info["total_url"])
    cache_path, last_mtime = Get_Current_Cache_Info(request_info["total_url"])
    request_info["cache_yes_no"] = cache_yes_no
    request_info["cache_path"] = cache_path
    request_info["last_mtime"] = last_mtime
    return request_info


# if cache is full then delete the least recently used cache item
def freeup_cache(file_requested):
    cache_files = os.listdir(CACHE_DIR)
    if len(cache_files) < MAX_CACHE_RECORDS:
        return
    last_mtime = min(memory[file][-1]["request_time"] for file in cache_files)
    file_to_del = [file for file in cache_files if memory[file][-1]["request_time"] == last_mtime][0]
    os.remove(CACHE_DIR + "/" + file_to_del)



'''
This function processes the client data and separates out the essential information
'''
def parse_request_info(client_addr, client_data):
    try:

        lines = client_data.splitlines()
        while lines[len(lines)-1] == '':
            lines.remove('')
        first_line_tokens = lines[0].split()
        url = first_line_tokens[1]

        url_pos = url.find("://")
        if url_pos != -1:
            protocol = url[:url_pos]
            url = url[(url_pos+3):]
        else:
            protocol = "http"

        # get port if any
        # get url path
        port_pos = url.find(":")
        path_pos = url.find("/")
        if path_pos == -1:
            path_pos = len(url)


        # change request path accordingly
        if port_pos==-1 or path_pos < port_pos:
            server_port = 80
            server_url = url[:path_pos]
        else:
            server_port = int(url[(port_pos+1):path_pos])
            server_url = url[:port_pos]

      

        # build up request for server
        first_line_tokens[1] = url[path_pos:]
        lines[0] = ' '.join(first_line_tokens)
        client_data = "\r\n".join(lines) + '\r\n\r\n'

        return {
            "server_port" : server_port,
            "server_url" : server_url,
            "total_url" : url,
            "client_data" : str.encode(client_data),
            "protocol" : protocol,
            "method" : first_line_tokens[0],
        }

    except Exception as e:
        print(e)
        print
        return None



# insert the header
def insert_if_modified(request_info):

    lines = str(request_info["client_data"],'utf-8' ).splitlines()
    while lines[len(lines)-1] == '':
        lines.remove('')

    header = time.strftime("%a %b %d %H:%M:%S %Y", request_info["last_mtime"])
    print("this is last_time "+ header )
    header = "If-Modified-Since: " + header
    lines.append(header)

    request_info["client_data"] = str.encode("\r\n".join(lines) + "\r\n\r\n")
    return request_info


def get_request_handler(client_socket, client_addr, request_info):
    try:
        client_data = request_info["client_data"]
        cache_yes_no = request_info["cache_yes_no"]
        cache_path = request_info["cache_path"]
        last_mtime = request_info["last_mtime"]

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.connect((request_info["server_url"], request_info["server_port"]))
        server_socket.send(request_info["client_data"])
        

        reply = server_socket.recv(RECV_SIZE)
        if last_mtime and "304 Not Modified" in str(reply, 'utf-8'):
            print("returning cached file "+ cache_path + " to address " + str(client_addr) )
            f = open(cache_path, 'rb')
            chunk = f.read(RECV_SIZE)
            while chunk:
                client_socket.send(chunk)
                chunk = f.read(RECV_SIZE)
            f.close()

        else:
            if cache_yes_no:
                print("Caching file " + cache_path  + " and sending to " + str(client_addr))
                freeup_cache(request_info["total_url"])
                f = open(cache_path, "w+")
                while len(reply):
                    client_socket.send(reply)
                    f.write(str(reply, 'utf-8'))
                    reply = server_socket.recv(RECV_SIZE)
                f.close()
                client_socket.send(str.encode("\r\n\r\n"))
                
            else:
                print("Not caching " + cache_path  +  " now, contacting server for request from client " + str(client_addr) )
                while len(reply):
                    client_socket.send(reply)
                    reply = server_socket.recv(RECV_SIZE)
                client_socket.send(str.encode("\r\n\r\n"))

        server_socket.close()
        client_socket.close()
        return

    except Exception as e:
        server_socket.close()
        client_socket.close()
        print(e)
        return


def post_request_handler(client_socket, client_addr, request_info):
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.connect((request_info["server_url"], request_info["server_port"]))
        server_socket.send(request_info["client_data"])

        while True:
            reply = server_socket.recv(RECV_SIZE)
            if len(reply):
                client_socket.send(reply)
            else:
                break

        server_socket.close()
        client_socket.close()
        return

    except Exception as e:
        server_socket.close()
        client_socket.close()
        print(e)
        return





def request_handler(client_socket, client_addr, client_data):

    request_info = parse_request_info(client_addr, client_data)

    if not request_info:
        print("There are no connection details")
        client_socket.close()
        return
    elif request_info["method"] == "GET":
        request_info = get_cache_request_info(client_addr, request_info)
        
        if request_info["last_mtime"]:
            request_info = insert_if_modified(request_info)
        get_request_handler(client_socket, client_addr, request_info)

    elif request_info["method"] == "POST":
        post_request_handler(client_socket, client_addr, request_info)

    client_socket.close()
    print(client_addr[0] +  " closed")




def proxy_handler():

    try:
        proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxy_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        proxy_socket.bind(('', PROXY_PORT))
        proxy_socket.listen(MAX_CONN)
        
        print("Startig proxy on "+ str(proxy_socket.getsockname()[0]) + " port " + str(proxy_socket.getsockname()[1])) 
        
    except Exception as e:
        print("Some Error Occured ...")
        print(e)
        proxy_socket.close()
        raise SystemExit


    # Main server loop
    while True:
        try:
            client_socket, client_addr = proxy_socket.accept()
            client_data = client_socket.recv(RECV_SIZE)
            print (str(client_addr[0] + ' '+ str(datetime.datetime.now()) + ' '+ str(client_data , 'utf-8')))

            _thread.start_new_thread(request_handler, (client_socket,client_addr,str(client_data , 'utf-8')))

        except KeyboardInterrupt:
            client_socket.close()
            proxy_socket.close()
            print("\nProxy server shutting down ...")
            break


proxy_handler()
