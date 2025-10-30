import wikipediaapi

wiki = wikipediaapi.Wikipedia('ja')
page = wiki.page("あさのゆきこ")

print("ページタイトル:", page.title)
print("存在する？:", page.exists())
print("概要の最初の100文字:", page.summary[:100])