import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import * as T from "three";
import { RaptorGuide } from "../components/raptorGuide.ts";

test("resting moves the head, keeps the feet planted, and gives way to an unprompted walk", () => {
  const body = new T.Group(),
    head = new T.Bone();
  head.name = "head";
  body.add(head);
  const mixer = new T.AnimationMixer(body);
  const idle = new T.AnimationClip("Idle", 2, [
    new T.NumberKeyframeTrack("head.rotation[y]", [0, 1, 2], [0, 0.25, 0]),
  ]);
  const guide = new RaptorGuide(
    body,
    mixer,
    new T.AnimationClip("Walk", 1, []),
    idle,
  );
  guide.appear(2, 0);
  const start = body.position.clone();
  guide.goTo(start.x, start.z);
  const camera = new T.Vector3(0, 2.4, start.z + 5);
  for (let i = 0; i < 30; i++) guide.step(1 / 60, camera);
  assert.ok(head.rotation.y > 0.05);
  assert.deepEqual(body.position, start);
  for (let i = 0; i < 240; i++) guide.step(1 / 60, camera);
  assert.ok(body.position.distanceTo(start) > 1);
});

test("shipped raptor includes keyed idle and walk clips", () => {
  const bytes = readFileSync(
    new URL("../public/hackervision/velociraptor.glb", import.meta.url),
  );
  const asset = JSON.parse(
    bytes.toString("utf8", 20, 20 + bytes.readUInt32LE(12)),
  );
  for (const name of ["Idle", "Walk"]) {
    const clip = asset.animations.find(
      (a: { name: string }) => a.name === name,
    );
    assert.ok(
      clip?.samplers.some(
        (s: { input: number }) => asset.accessors[s.input].count > 1,
      ),
      name,
    );
  }
});
