#!/usr/bin/env node
// Concatenate one or more earth-flyover clips into a single video, embed the combined
// segment list as MP4 chapter markers, and emit sidecar files for post-processing
// (adding lower-thirds/graphics for each hole in an NLE).
//
// Usage:
//   node stitch.mjs --out FINAL.mp4 clip1.mp4 [clip2.mp4 ...]
//
// Each clipN.mp4 is expected to have a companion clipN.segments.json manifest --
// written automatically by render.mjs alongside its video output. Clips without one
// are treated as a single unlabeled segment spanning that clip's full duration.
//
// Outputs:
//   FINAL.mp4            the concatenated video with embedded MP4 chapter markers
//   FINAL.chapters.json  full merged segment list with global timestamps + hole
//                        metadata (par/distance/note) -- for scripted post-processing
//   FINAL.srt            one subtitle-format cue per segment (label only) -- universal,
//                         drag-and-drop into any NLE as a caption/marker reference track
import { execFileSync } from 'child_process';
import { readFileSync, writeFileSync, existsSync, mkdtempSync, rmSync } from 'fs';
import path from 'path';
import os from 'os';

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--out') out.out = argv[++i];
    else out._.push(a);
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const clips = args._;
if (!args.out || clips.length === 0) {
  console.error('Usage: node stitch.mjs --out FINAL.mp4 clip1.mp4 [clip2.mp4 ...]');
  process.exit(1);
}
const OUT_FILE = path.resolve(args.out);

function ffprobeDuration(file) {
  const out = execFileSync('ffprobe', [
    '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file
  ]).toString().trim();
  return parseFloat(out);
}

function pad(n, w = 2) { return String(n).padStart(w, '0'); }
function srtTime(sec) {
  const ms = Math.max(0, Math.round(sec * 1000));
  const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000), s = Math.floor((ms % 60000) / 1000);
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad(ms % 1000, 3)}`;
}
function segLabel(seg) {
  const bits = [seg.label];
  if (seg.par != null && seg.distance) bits.push(`(Par ${seg.par}, ${seg.distance})`);
  return bits.join(' ');
}

// --- gather clip durations + segment manifests, compute global (cumulative) offsets ---
let cumulative = 0;
const allSegments = [];
for (const clip of clips) {
  const manifestPath = clip.replace(/\.mp4$/i, '') + '.segments.json';
  const duration = ffprobeDuration(clip);
  let segs;
  if (existsSync(manifestPath)) {
    segs = JSON.parse(readFileSync(manifestPath, 'utf8')).segments;
  } else {
    console.log(`no segments manifest for ${clip} -- treating as one unlabeled segment`);
    segs = [{ label: path.basename(clip, '.mp4'), startSec: 0, endSec: duration }];
  }
  for (const s of segs) allSegments.push({ ...s, startSec: s.startSec + cumulative, endSec: s.endSec + cumulative });
  cumulative += duration;
}
console.log(`${clips.length} clip(s), ${allSegments.length} total segment(s), ${cumulative.toFixed(2)}s combined`);

// --- concatenate. Always via the concat FILTER (decode+re-encode), not the concat
// demuxer's stream-copy, so mismatched clip resolutions/fps/pix_fmt don't silently
// break -- more robust at the cost of one extra encode pass. ---
const tmpDir = mkdtempSync(path.join(os.tmpdir(), 'stitch-'));
const concatFile = path.join(tmpDir, 'concat.mp4');

if (clips.length === 1) {
  execFileSync('ffmpeg', ['-y', '-i', clips[0], '-c', 'copy', concatFile]);
} else {
  const inputArgs = clips.flatMap((c) => ['-i', c]);
  const filterInputs = clips.map((_, i) => `[${i}:v:0]`).join('');
  const filter = `${filterInputs}concat=n=${clips.length}:v=1:a=0[outv]`;
  console.log('concatenating', clips.length, 'clips...');
  execFileSync('ffmpeg', [
    '-y', ...inputArgs,
    '-filter_complex', filter, '-map', '[outv]',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'slow',
    concatFile
  ], { stdio: 'inherit' });
}

// --- embed the merged segment list as MP4 chapter markers ---
const chapterLines = [';FFMETADATA1'];
for (const seg of allSegments) {
  chapterLines.push('', '[CHAPTER]', 'TIMEBASE=1/1000',
    `START=${Math.round(seg.startSec * 1000)}`, `END=${Math.round(seg.endSec * 1000)}`, `title=${segLabel(seg)}`);
}
const chapterFile = path.join(tmpDir, 'chapters.txt');
writeFileSync(chapterFile, chapterLines.join('\n') + '\n');

console.log('muxing chapters ->', OUT_FILE);
execFileSync('ffmpeg', [
  '-y', '-i', concatFile, '-i', chapterFile,
  '-map_metadata', '1', '-map', '0',
  '-c', 'copy', '-movflags', '+faststart',
  OUT_FILE
], { stdio: 'inherit' });

rmSync(tmpDir, { recursive: true, force: true });

// --- sidecars ---
const chaptersJsonPath = OUT_FILE.replace(/\.mp4$/i, '') + '.chapters.json';
writeFileSync(chaptersJsonPath, JSON.stringify({ durationSeconds: cumulative, segments: allSegments }, null, 2));

const srtPath = OUT_FILE.replace(/\.mp4$/i, '') + '.srt';
const srtLines = [];
allSegments.forEach((seg, i) => srtLines.push(String(i + 1), `${srtTime(seg.startSec)} --> ${srtTime(seg.endSec)}`, segLabel(seg), ''));
writeFileSync(srtPath, srtLines.join('\n'));

console.log('done ->', OUT_FILE);
console.log('chapters json ->', chaptersJsonPath);
console.log('srt ->', srtPath);
