
#出力ファイルの読み込み
try:
    f = open('output.txt','r', encoding='UTF-8')
    date=f.read()
except:
    print("出力ファイルが読み込めませんでした。")
    
print("それは"+date+"ですか？")