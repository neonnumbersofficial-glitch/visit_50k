from flask import Flask, jsonify
import aiohttp
import asyncio
import json
import os
import sys
import time
from functools import lru_cache
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "online",
        "endpoint": "/visit/<server>/<uid>",
        "example": "/visit/bd/14502384617",
        "target": "50,000 visits"
    }), 200

@lru_cache(maxsize=5)
def load_tokens(server_name):
    try:
        path_map = {
            "IND": "token_ind.json",
            "BR": "token_br.json",
            "US": "token_br.json",
            "SAC": "token_br.json",
            "NA": "token_br.json",
            "BD": "token_bd.json"
        }
        path = path_map.get(server_name.upper(), "token_bd.json")

        with open(path, "r") as f:
            data = json.load(f)

        tokens = [item["token"] for item in data if item.get("token") not in ["", "N/A", None]]
        print(f"✅ Loaded {len(tokens)} tokens for {server_name}")
        return tokens
    except Exception as e:
        print(f"❌ Token load error: {e}")
        return []

def get_url(server_name):
    server = server_name.upper()
    url_map = {
        "IND": "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
        "BR": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "US": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "SAC": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "NA": "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    }
    return url_map.get(server, "https://clientbp.ggblueshark.com/GetPlayerPersonalShow")

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
    except:
        return None

async def visit(session, url, token, data):
    headers = {
        "ReleaseVersion": "OB53",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False, timeout=10) as resp:
            if resp.status == 200:
                return True, await resp.read()
            return False, None
    except:
        return False, None

async def send_visits_async(tokens, uid, server_name, target=50000):
    url = get_url(server_name)
    token_len = len(tokens)
    
    encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
    data = bytes.fromhex(encrypted)
    
    success = 0
    sent = 0
    fail = 0
    player_info = None
    
    connector = aiohttp.TCPConnector(limit=100, ssl=False)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        while success < target:
            batch = min(target - success, 200)
            tasks = []
            
            for i in range(batch):
                token = tokens[(sent + i) % token_len]
                tasks.append(visit(session, url, token, data))
            
            results = await asyncio.gather(*tasks)
            
            if player_info is None:
                for ok, resp in results:
                    if ok and resp:
                        player_info = parse_protobuf_response(resp)
                        break
            
            for ok, _ in results:
                sent += 1
                if ok:
                    success += 1
                else:
                    fail += 1
            
            print(f"Progress: {success}/{target} | Failed: {fail}")
            sys.stdout.flush()
            
            if success == 0 and sent > 5000:
                break
    
    return success, sent, fail, player_info

@app.route('/visit/<string:server>/<int:uid>', methods=['GET'])
def visit_endpoint(server, uid):
    start_time = time.time()
    server = server.upper()
    target = 50000
    
    print(f"📥 Visit request: server={server}, uid={uid}, target={target}")
    sys.stdout.flush()
    
    tokens = load_tokens(server)
    if not tokens:
        return jsonify({"error": f"No tokens found for server: {server}"}), 500
    
    try:
        success, sent, fail, player_info = asyncio.run(
            send_visits_async(tokens, uid, server, target)
        )
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.stdout.flush()
        return jsonify({"error": str(e)}), 500
    
    elapsed = round(time.time() - start_time, 2)
    
    response = {
        "status": "completed",
        "target": target,
        "success": success,
        "fail": fail,
        "total_sent": sent,
        "time_seconds": elapsed,
        "time_minutes": round(elapsed/60, 2),
        "success_rate": f"{round((success/sent)*100, 1)}%" if sent > 0 else "0%"
    }
    
    if player_info:
        response["player"] = {
            "uid": player_info.get("uid", uid),
            "nickname": player_info.get("nickname", ""),
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "region": player_info.get("region", "")
        }
    
    return jsonify(response), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5100))
    print(f"🚀 Server running on port {port}")
    print(f"📌 Endpoint: http://localhost:{port}/visit/<server>/<uid>")
    print(f"📌 Example: http://localhost:{port}/visit/bd/14502384617")
    print(f"📌 Target: 50,000 visits per request")
    sys.stdout.flush()
    app.run(host="0.0.0.0", port=port, threaded=True)
