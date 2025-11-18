from resolver import resolve_classplus

link = "https://media-cdn.classplusapp.com/1005566/cc/acc5916a6f7a4a5d9b22281817eca927-mg/master.m3u8"

signed = resolve_classplus(link)
print("Signed URL:", signed)
