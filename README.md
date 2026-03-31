# WXYC-Archive

Automated audio recording and archiving for WXYC 89.3 FM. Runs on a Raspberry Pi to capture the broadcast, encode it, and upload hourly segments to S3.

## How It Works

A cron job runs `record_audio.pl` every hour, which:

1. Records 3600 seconds of audio from the sound card via `arecord`
2. Encodes the recording to FLAC (local archive) and MP3
3. Uploads the MP3 to the `s3://wxyc-archive/` bucket, organized by date
4. Cleans up the temporary WAV file

## Files

| File | Description |
|------|-------------|
| `record_audio.pl` | Main recording/encoding/upload script |
| `cron_file` | Crontab entry that triggers hourly recording |

## Prerequisites

- Perl (with `DateTime`, `Getopt::Long`, `File::Spec`, `File::Path`)
- `arecord` (ALSA utils) for audio capture
- `flac` for FLAC encoding
- `lame` for MP3 encoding
- AWS CLI (configured with credentials for S3 uploads)

## Usage

Install the cron job:

```bash
crontab cron_file
```

Test with a short recording in debug mode:

```bash
./record_audio.pl -l 10 --debug
```
