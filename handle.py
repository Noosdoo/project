
#出力ファイルの読み込み
try:
    f = open('output.txt','r', encoding='UTF-8')
    date=f.read()
except:
    print("出力ファイルが読み込めませんでした。")
    
#選択肢入力    
input=input("それは"+date+"ですか？\n")

# ファイルを開く（存在しなければ新規作成）
with open("input.txt", "w", encoding="utf-8") as f:
    f.write(input)
