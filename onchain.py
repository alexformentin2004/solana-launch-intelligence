"""Best-effort public Solana RPC token mint checks; no wallet or trading operations."""
import base64
import json
import os
import struct
import urllib.request

RPC = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
SPL_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFzNvD3UpPWqS4pZ"  # validation uses owner checks

def mint_checks(mint):
    body = json.dumps({"jsonrpc":"2.0","id":1,"method":"getAccountInfo",
                       "params":[mint,{"encoding":"base64","commitment":"confirmed"}]}).encode()
    req = urllib.request.Request(RPC,body,{"Content-Type":"application/json","User-Agent":"solana-launch-intelligence/2.0"})
    with urllib.request.urlopen(req,timeout=12) as res:
        obj=json.load(res)
    if obj.get("error"):
        raise ValueError("RPC returned an error")
    account=(obj.get("result") or {}).get("value")
    if not account:
        raise ValueError("Mint account not found")
    owner=account.get("owner","")
    if owner != SPL_TOKEN:
        # Token-2022 and other programs require extension-aware decoding; don't guess.
        return {"token_program":owner,"mint_authority":None,"freeze_authority":None,
                "mint_authority_present":None,"freeze_authority_present":None,
                "status":"unsupported_program"}
    data=base64.b64decode(account["data"][0],validate=True)
    if len(data)!=82:
        raise ValueError("Unexpected SPL mint account size")
    mint_flag=struct.unpack_from("<I",data,0)[0]
    freeze_flag=struct.unpack_from("<I",data,46)[0]
    if mint_flag not in (0,1) or freeze_flag not in (0,1):
        raise ValueError("Invalid mint authority flags")
    return {"token_program":owner,"mint_authority":base64.b64encode(data[4:36]).decode() if mint_flag else None,
            "freeze_authority":base64.b64encode(data[50:82]).decode() if freeze_flag else None,
            "mint_authority_present":bool(mint_flag),"freeze_authority_present":bool(freeze_flag),
            "status":"verified"}
