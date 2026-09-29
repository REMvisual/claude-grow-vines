"""uemcp.py -- raw Streamable-HTTP client for Epic's UE 5.8 ModelContextProtocol server.

Uses http.client (urllib returns an EMPTY body for the server's chunked text/event-stream
tools/call replies). Usage as a library:
    import uemcp; c = uemcp.Client("127.0.0.1", 8001); c.init()
    c.list_toolsets(); c.describe("editor_toolset.toolsets.asset.AssetTools")
    c.call("editor_toolset.toolsets.asset.AssetTools", "exists", {"asset_path": "/Game/X"})
"""
import http.client, json, sys


class Client:
    def __init__(self, host="127.0.0.1", port=8001, path="/mcp", timeout=900):
        self.host, self.port, self.path, self.timeout = host, port, path, timeout
        self.sid = None
        self._id = 0

    def _post(self, body, notify=False):
        hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            hdr["Mcp-Session-Id"] = self.sid
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        conn.request("POST", self.path, body=json.dumps(body), headers=hdr)
        r = conn.getresponse()
        sid = r.getheader("Mcp-Session-Id")
        if sid:
            self.sid = sid
        raw = r.read().decode("utf-8", "replace")
        ctype = r.getheader("Content-Type") or ""
        conn.close()
        if notify:
            return None
        if "text/event-stream" in ctype:
            msgs = []
            for line in raw.splitlines():
                if line.startswith("data:"):
                    try:
                        msgs.append(json.loads(line[5:].strip()))
                    except Exception:
                        pass
            for m in msgs:
                if m.get("id") == body.get("id"):
                    return m
            return msgs[-1] if msgs else {"raw": raw, "status": r.status}
        return json.loads(raw) if raw.strip() else {"raw": raw, "status": r.status}

    def rpc(self, method, params=None):
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            body["params"] = params
        return self._post(body)

    def init(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "pfg-uemcp", "version": "0.1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notify=True)
        return r

    @staticmethod
    def _unwrap(resp):
        """tools/call replies carry the payload as JSON text in result.content[0].text."""
        if not isinstance(resp, dict):
            return resp
        if "error" in resp:
            return {"error": resp["error"]}
        res = resp.get("result", resp)
        if isinstance(res, dict) and "structuredContent" in res:
            return res["structuredContent"]
        if isinstance(res, dict) and "content" in res:
            out = []
            for c in res["content"]:
                if c.get("type") == "text":
                    try:
                        out.append(json.loads(c["text"]))
                    except Exception:
                        out.append(c["text"])
            if res.get("isError"):
                return {"error": out}
            return out[0] if len(out) == 1 else out
        return res

    def tool(self, name, arguments=None):
        return self._unwrap(self.rpc("tools/call", {"name": name, "arguments": arguments or {}}))

    def list_toolsets(self):
        return self.tool("list_toolsets")

    def describe(self, toolset):
        return self.tool("describe_toolset", {"toolset_name": toolset})

    def call(self, toolset, tool, arguments=None):
        a = {"tool_name": tool, "arguments": arguments or {}}
        if toolset:
            a["toolset_name"] = toolset
        return self.tool("call_tool", a)


if __name__ == "__main__":
    c = Client(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8001)
    c.init()
    ts = c.list_toolsets()
    print(json.dumps(ts, indent=1)[:12000])
