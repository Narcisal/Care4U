# Taiwanese STT Verification

Date: 2026-06-02  
Environment: Windows local demo environment

## Scope

This verification checks whether the Taiwanese STT route can be selected and whether Breeze ASR 26 can be loaded by the backend.

It does not measure real microphone transcription accuracy. Accuracy still requires a real Taiwanese speech sample.

## API Checks

### `GET /api/stt/status`

Result:

- `torch_available`: true
- `transformers_available`: true
- `breeze_cache_exists`: true
- `taiwanese_stt_verified`: true
- `whisper_available`: false in the current Python runtime
- `torchaudio_available`: false in the current Python runtime
- `soundfile_available`: false in the current Python runtime

The STT service was adjusted so the diagnostic endpoint can still report readiness even when optional audio packages are missing.

### `POST /api/stt/language`

Request:

```json
{
  "elder_id": "W001",
  "language": "tai"
}
```

Result:

- `success`: true
- `language`: `tai`
- `breeze_loaded`: true
- `verification_note`: `Taiwanese STT route verified with Breeze ASR loaded.`

## Conclusion

Taiwanese STT route verification passed at the API/model-loading level.

The system can switch to Taiwanese STT mode and load Breeze ASR 26 without breaking the backend. Live transcription quality should be tested later with a 5-10 second Taiwanese recording before using it as a primary demo feature.
