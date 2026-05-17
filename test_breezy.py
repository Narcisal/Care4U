from backend.services.tts_service import TTSService
tts = TTSService()
tts.set_engine('breezyvoice')
audio = tts.synthesize('爺爺你好，我是小玲，你今天感覺怎麼樣？')
with open('test_breezy.wav', 'wb') as f:
    f.write(audio)
print('完成！')