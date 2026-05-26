#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#define MINIMP3_IMPLEMENTATION
#include "minimp3_ex.h"

static void write_u16(FILE *f, uint16_t v) {
    fputc(v & 255, f);
    fputc((v >> 8) & 255, f);
}

static void write_u32(FILE *f, uint32_t v) {
    fputc(v & 255, f);
    fputc((v >> 8) & 255, f);
    fputc((v >> 16) & 255, f);
    fputc((v >> 24) & 255, f);
}

static double mono_sample(const mp3d_sample_t *buffer, size_t frame, int channels) {
    if (channels == 1) {
        return (double)buffer[frame];
    }
    double sum = 0.0;
    for (int c = 0; c < channels; c++) {
        sum += (double)buffer[frame * (size_t)channels + (size_t)c];
    }
    return sum / (double)channels;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input.mp3> <output.wav>\n", argv[0]);
        return 2;
    }

    mp3dec_t dec;
    mp3dec_file_info_t info;
    mp3dec_init(&dec);
    int ret = mp3dec_load(&dec, argv[1], &info, NULL, NULL);
    if (ret != 0) {
        fprintf(stderr, "mp3dec_load failed: %d\n", ret);
        return 1;
    }
    if (info.channels < 1 || info.hz < 1 || info.samples == 0) {
        fprintf(stderr, "bad mp3 info\n");
        free(info.buffer);
        return 1;
    }

    const int target_hz = 16000;
    const int target_channels = 1;
    const int bits_per_sample = 16;
    const size_t src_frames = info.samples / (size_t)info.channels;
    const size_t out_frames = (size_t)floor((double)src_frames * (double)target_hz / (double)info.hz);
    int16_t *out = (int16_t *)calloc(out_frames, sizeof(int16_t));
    if (!out) {
        fprintf(stderr, "out of memory\n");
        free(info.buffer);
        return 1;
    }

    for (size_t i = 0; i < out_frames; i++) {
        double src_pos = (double)i * (double)info.hz / (double)target_hz;
        size_t idx = (size_t)floor(src_pos);
        double frac = src_pos - (double)idx;
        if (idx + 1 >= src_frames) {
            idx = src_frames - 2;
            frac = 1.0;
        }
        double a = mono_sample(info.buffer, idx, info.channels);
        double b = mono_sample(info.buffer, idx + 1, info.channels);
        double sample = a + (b - a) * frac;
        if (sample > 32767.0) sample = 32767.0;
        if (sample < -32768.0) sample = -32768.0;
        out[i] = (int16_t)lrint(sample);
    }

    FILE *f = fopen(argv[2], "wb");
    if (!f) {
        perror("fopen output");
        free(out);
        free(info.buffer);
        return 1;
    }

    const uint32_t data_bytes = (uint32_t)(out_frames * target_channels * (bits_per_sample / 8));
    fwrite("RIFF", 1, 4, f);
    write_u32(f, 36 + data_bytes);
    fwrite("WAVE", 1, 4, f);
    fwrite("fmt ", 1, 4, f);
    write_u32(f, 16);
    write_u16(f, 1);
    write_u16(f, target_channels);
    write_u32(f, target_hz);
    write_u32(f, target_hz * target_channels * (bits_per_sample / 8));
    write_u16(f, target_channels * (bits_per_sample / 8));
    write_u16(f, bits_per_sample);
    fwrite("data", 1, 4, f);
    write_u32(f, data_bytes);
    fwrite(out, sizeof(int16_t), out_frames, f);
    fclose(f);

    fprintf(stderr, "decoded %zu frames at %d Hz/%d ch -> %zu frames at %d Hz mono\n",
            src_frames, info.hz, info.channels, out_frames, target_hz);
    free(out);
    free(info.buffer);
    return 0;
}
