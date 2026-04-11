from flask import Flask, jsonify
import aiohttp
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import uvloop
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info

# Install uvloop for faster async operations
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

app = Flask(__name__)

# Cache token loading
@lru_cache(maxsize=10)
def load_tokens(server_name):
    try:
        path_map = {
            "IND": "token_ind.json",
            "BR": "token_br.json",
            "US": "token_br.json",
            "SAC": "token_br.json",
            "NA": "token_br.json"
        }
        path = path_map.get(server_name, "token_bd.json")

        with open(path, "r") as f:
            data = json.load(f)

        tokens = [item["token"] for item in data if item.get("token") not in ["", "N/A", None]]
        return tokens
    except Exception as e:
        app.logger.error(f"❌ Token load error for {server_name}: {e}")
        return []

# Cache URL mapping
@lru_cache(maxsize=10)
def get_url(server_name):
    url_map = {
        "IND": "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
        "BR": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "US": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "SAC": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "NA": "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    }
    return url_map.get(server_name, "https://clientbp.ggblueshark.com/GetPlayerPersonalShow")

def parse_protobuf_response(response_data):
    try:
        info = Info()
        info.ParseFromString(response_data)
        
        return {
            "uid": info.AccountInfo.UID or 0,
            "nickname": info.AccountInfo.PlayerNickname or "",
            "likes": info.AccountInfo.Likes or 0,
            "region": info.AccountInfo.PlayerRegion or "",
            "level": info.AccountInfo.Levels or 0
        }
    except Exception as e:
        app.logger.error(f"❌ Protobuf parsing error: {e}")
        return None

async def visit(session, url, token, uid, encrypted_data, semaphore):
    headers = {
        "ReleaseVersion": "OB53",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    
    async with semaphore:
        try:
            async with session.post(url, headers=headers, data=encrypted_data, ssl=False) as resp:
                if resp.status == 200:
                    return True, await resp.read()
                return False, None
        except:
            return False, None

async def send_until_success(tokens, uid, server_name, target_success=2000):
    url = get_url(server_name)
    connector = aiohttp.TCPConnector(
        limit=0,
        ttl_dns_cache=300,
        force_close=True,
        enable_cleanup_closed=True
    )
    
    semaphore = asyncio.Semaphore(1000)  # Limit concurrent connections
    total_success = 0
    total_sent = 0
    first_success_response = None
    player_info = None
    token_len = len(tokens)
    
    # Pre-encrypt data once
    encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
    encrypted_data = bytes.fromhex(encrypted)
    
    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        trust_env=True
    ) as session:
        
        while total_success < target_success:
            batch_size = min(target_success - total_success, 2000)
            
            # Create tasks more efficiently
            tasks = [
                visit(
                    session, url, 
                    tokens[(total_sent + i) % token_len], 
                    uid, encrypted_data, semaphore
                )
                for i in range(batch_size)
            ]
            
            # Use return_exceptions for better performance
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            if first_success_response is None:
                for result in results:
                    if isinstance(result, tuple) and result[0] and result[1]:
                        first_success_response = result[1]
                        player_info = parse_protobuf_response(result[1])
                        break
            
            batch_success = sum(1 for r in results if isinstance(r, tuple) and r[0])
            total_success += batch_success
            total_sent += batch_size

            print(f"Batch sent: {batch_size}, Success: {batch_success}, Total: {total_success}")

    return total_success, total_sent, player_info

@app.route('/<string:server>/<int:uid>', methods=['GET'])
def send_visits(server, uid):
    server = server.upper()
    tokens = load_tokens(server)
    target_success = 2000

    if not tokens:
        return jsonify({"error": "❌ No valid tokens found"}), 500

    print(f"🚀 Sending visits to UID: {uid} using {len(tokens)} tokens")

    try:
        total_success, total_sent, player_info = asyncio.run(
            send_until_success(tokens, uid, server, target_success)
        )
    except Exception as e:
        return jsonify({"error": f"Execution error: {str(e)}"}), 500

    if player_info:
        return jsonify({
            "fail": target_success - total_success,
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "nickname": player_info.get("nickname", ""),
            "region": player_info.get("region", ""),
            "success": total_success,
            "uid": player_info.get("uid", 0)
        }), 200
    else:
        return jsonify({"error": "Could not decode player information"}), 500

if __name__ == "__main__":
    # Use multiple workers for production
    from multiprocessing import cpu_count
    app.run(
        host="0.0.0.0", 
        port=5100,
        threaded=True,
        processes=cpu_count()  # Use multiple processes
    )
