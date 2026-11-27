import * as T from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { type FrameEvent, stations } from "@/lib/mainframe";

import { RaptorGuide } from "./raptorGuide";

function cabinetFace(label: string, evidence: boolean) {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 384;
  const g = canvas.getContext("2d");
  if (!g) throw new Error("Cabinet texture unavailable");
  g.fillStyle = "#303e41";
  g.fillRect(0, 0, 256, 384);
  g.fillStyle = evidence ? "#dbc7a2" : "#a5d1be";
  g.fillRect(9, 10, 238, 49);
  g.fillStyle = "#142725";
  g.font = "bold 22px monospace";
  g.fillText(label.toUpperCase(), 17, 41);
  g.fillStyle = "#0f2524";
  g.fillRect(10, 70, 236, 95);
  g.fillStyle = evidence ? "#e4b87a" : "#93ecbf";
  g.font = "17px monospace";
  g.fillText(evidence ? "EVIDENCE" : "OPERATIONS", 20, 107);
  for (let y = 184; y < 366; y += 25) {
    g.fillStyle = "#142222";
    g.fillRect(11, y, 234, 19);
    g.fillStyle = "#566e65";
    g.fillRect(18, y + 5, 148, 2);
    g.fillStyle = "#a4c8ad";
    g.fillRect(202, y + 7, 16, 3);
  }
  const texture = new T.CanvasTexture(canvas);
  texture.colorSpace = T.SRGBColorSpace;
  return new T.MeshBasicMaterial({ map: texture });
}

function release(root: T.Object3D) {
  const geometries = new Set<T.BufferGeometry>(),
    materials = new Set<T.Material>();
  root.traverse((obj) => {
    if (obj instanceof T.Mesh || obj instanceof T.LineSegments) {
      geometries.add(obj.geometry);
      for (const m of Array.isArray(obj.material)
        ? obj.material
        : [obj.material])
        materials.add(m);
      if (obj instanceof T.SkinnedMesh) obj.skeleton.dispose();
    }
  });
  for (const g of geometries) g.dispose();
  for (const m of materials) {
    if ("map" in m && m.map instanceof T.Texture) m.map.dispose();
    m.dispose();
  }
}

export function mountScene(
  canvas: HTMLCanvasElement,
  inspect: (id: string) => void,
  manual: () => void,
  modelError: () => void,
) {
  const renderer = new T.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  const scene = new T.Scene(),
    camera = new T.PerspectiveCamera(53, 1, 0.08, 100);
  scene.background = new T.Color("#132a2a");
  scene.fog = new T.FogExp2("#132a2a", 0.038);
  scene.add(new T.HemisphereLight(0xe1ffed, 0x607c78, 2.2));
  const sun = new T.DirectionalLight(0xffecc0, 2.5);
  sun.position.set(-5, 10, 6);
  scene.add(sun);
  const geometry = new T.BoxGeometry();
  const metal = new T.MeshStandardMaterial({ color: 0x526663, roughness: 0.8 });
  const base = new T.MeshStandardMaterial({ color: 0x253736 });
  function box(
    x: number,
    y: number,
    z: number,
    w: number,
    h: number,
    d: number,
    mat: T.Material | T.Material[],
  ) {
    const mesh = new T.Mesh(geometry, mat);
    mesh.position.set(x, y, z);
    mesh.scale.set(w, h, d);
    scene.add(mesh);
    return mesh;
  }
  const floor = box(0, -0.31, -13, 85, 0.6, 78, base);
  const glow = new T.PointLight(0xffcb8e, 13, 8);
  scene.add(glow);
  glow.visible = false;
  const shadowCanvas = document.createElement("canvas");
  shadowCanvas.width = shadowCanvas.height = 64;
  const ink = shadowCanvas.getContext("2d");
  if (ink) {
    const fade = ink.createRadialGradient(32, 32, 2, 32, 32, 32);
    fade.addColorStop(0, "rgba(0,0,0,.62)");
    fade.addColorStop(0.55, "rgba(0,0,0,.33)");
    fade.addColorStop(1, "rgba(0,0,0,0)");
    ink.fillStyle = fade;
    ink.fillRect(0, 0, 64, 64);
  }
  const shadow = new T.Mesh(
    new T.PlaneGeometry(1.15, 2.65),
    new T.MeshBasicMaterial({
      map: new T.CanvasTexture(shadowCanvas),
      transparent: true,
      depthWrite: false,
    }),
  );
  shadow.rotation.order = "YXZ";
  shadow.rotation.x = -Math.PI / 2;
  shadow.visible = false;
  scene.add(shadow);
  const grid = new T.GridHelper(82, 82, 0x729989, 0x38564e);
  grid.position.z = -13;
  scene.add(grid);
  const bus = new T.MeshBasicMaterial({ color: 0x7db89b });
  for (const x of [-0.55, -0.42, 0.42, 0.55])
    box(x, 0.026, -10, 0.035, 0.025, 45, bus);
  const packet = box(
    0,
    0.13,
    5,
    0.14,
    0.14,
    0.45,
    new T.MeshBasicMaterial({ color: 0xbaffd7 }),
  );
  packet.visible = false;
  let packetStarted = -Infinity,
    packetId: string | undefined;
  const lamps: T.MeshBasicMaterial[] = [];
  const racks = Array.from({ length: 12 }, (_, i) => {
    const z = 2 - Math.floor(i / 2) * 4.3,
      x = i % 2 ? 3.3 : -3.3;
    const face = cabinetFace(stations[Math.floor(i / 2)], i % 2 === 1);
    box(x, 0.2, z, 3.1, 0.4, 2.8, base);
    const rack = box(x, 1.93, z, 2.75, 3.1, 2.5, [
      face,
      face,
      metal,
      metal,
      face,
      metal,
    ]);
    const lamp = new T.MeshBasicMaterial({ color: 0x38504a });
    lamps.push(lamp);
    box(x, 3.55, z, 2.7, 0.11, 2.45, lamp);
    rack.userData.bank = i;
    box(x / 2, 0.04, z, Math.abs(x), 0.025, 0.045, bus);
    return rack;
  });
  for (let j = 0; j < 10; j++)
    for (const side of [-1, 1])
      box(side * 8, 2.2, 5 - j * 4.5, 3, 4.4, 3.5, metal);
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let animateInReducedMotion = false;
  const raptorMoves = () => !motion.matches || animateInReducedMotion;
  let disposed = false,
    following = true,
    yaw = 0,
    pitch = -0.13,
    station = 0,
    side = 0,
    frame = 0,
    prev = 0;
  let active = false,
    loading = false,
    raptor: T.Group | undefined,
    mixer: T.AnimationMixer | undefined,
    guide: RaptorGuide | undefined;
  let banks: (FrameEvent | undefined)[] = [];
  camera.rotation.order = "YXZ";
  camera.position.set(0, 2.4, 8);
  function loadRaptor() {
    if (loading) return;
    loading = true;
    new GLTFLoader().load(
      "/hackervision/velociraptor.glb?motion=2",
      (g) => {
        if (disposed) {
          release(g.scene);
          return;
        }
        raptor = g.scene;
        const bounds = new T.Box3().setFromObject(raptor);
        const height = bounds.getSize(new T.Vector3()).y;
        raptor.scale.setScalar(1.35 / height);
        scene.add(raptor);
        mixer = new T.AnimationMixer(raptor);
        const walk = T.AnimationClip.findByName(g.animations, "Walk");
        const idle = T.AnimationClip.findByName(g.animations, "Idle");
        if (walk && idle) {
          guide = new RaptorGuide(raptor, mixer, walk, idle);
          guide.appear(station, side);
        }
        wake();
      },
      undefined,
      () => {
        if (!disposed) modelError();
      },
    );
  }
  const keys = new Set<string>();
  function advance(distance: number) {
    camera.position.x = T.MathUtils.clamp(
      camera.position.x - Math.sin(yaw) * distance,
      -1.55,
      1.55,
    );
    camera.position.z = T.MathUtils.clamp(
      camera.position.z - Math.cos(yaw) * distance,
      -24,
      9,
    );
  }
  function draw(now: number) {
    frame = 0;
    const dt = prev ? Math.min(0.25, (now - prev) / 1000) : 1 / 60;
    prev = now;
    const targetZ = 7.1 - station * 4.3,
      targetYaw = side ? -0.36 : 0.36;
    if (following) {
      const blend = motion.matches ? 1 : 1 - Math.exp(-dt * 4);
      camera.position.lerp(new T.Vector3(0, 2.4, targetZ), blend);
      yaw += (targetYaw - yaw) * blend;
      pitch += (-0.15 - pitch) * blend;
    } else {
      const held = (a: string, b: string) => Number(keys.has(a) || keys.has(b));
      yaw += (held("a", "arrowleft") - held("d", "arrowright")) * dt * 1.7;
      const walk = (held("w", "arrowup") - held("s", "arrowdown")) * dt * 5;
      advance(walk);
    }
    camera.rotation.set(pitch, yaw, 0);
    if (raptor) {
      raptor.visible = shadow.visible = glow.visible = active;
      if (active) {
        if (raptorMoves() && guide) {
          const steps = Math.ceil(dt * 30);
          for (let i = 0; i < steps; i++)
            guide.step(dt / steps, camera.position);
        }
        shadow.position.set(raptor.position.x, 0.018, raptor.position.z);
        shadow.rotation.y = raptor.rotation.y;
        glow.position.copy(raptor.position);
        glow.position.x -= 1.2;
        glow.position.y += 2.8;
        glow.position.z += 1.8;
      }
    }
    const fraction = (now - packetStarted) / 950;
    packet.visible = fraction >= 0 && fraction < 1 && !motion.matches;
    if (packet.visible) {
      const target = racks[station * 2 + side].position;
      const turn = T.MathUtils.clamp((fraction - 0.7) / 0.3, 0, 1);
      packet.position.set(
        target.x * turn,
        0.13,
        7 + (target.z - 7) * Math.min(1, fraction / 0.7),
      );
      packet.rotation.y = turn > 0 ? Math.PI / 2 : 0;
    }
    renderer.render(scene, camera);
    if (
      packet.visible ||
      keys.size ||
      (active && guide && raptorMoves()) ||
      (following &&
        Math.abs(camera.position.z - targetZ) +
          Math.abs(camera.position.x) +
          Math.abs(yaw - targetYaw) +
          Math.abs(pitch + 0.15) >
          0.006)
    )
      wake();
  }
  function wake() {
    if (!disposed && !frame) frame = requestAnimationFrame(draw);
  }
  function resize() {
    const { clientWidth: w, clientHeight: h } = canvas;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    wake();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();
  function directRaptor(x: number, z: number) {
    if (!guide || !active) return;
    guide.goTo(x, z);
    if (!raptorMoves()) guide.model.position.copy(guide.destination);
    wake();
  }
  const ray = new T.Raycaster();
  let pointer: {
    x: number;
    y: number;
    angle: number;
    pitch: number;
    moved: boolean;
  } | null = null;
  canvas.onpointerdown = (e) => {
    canvas.focus();
    canvas.setPointerCapture(e.pointerId);
    pointer = { x: e.clientX, y: e.clientY, angle: yaw, pitch, moved: false };
  };
  canvas.onpointermove = (e) => {
    if (!pointer) return;
    const x = e.clientX - pointer.x,
      y = e.clientY - pointer.y;
    if (!pointer.moved && Math.hypot(x, y) < 5) return;
    pointer.moved = true;
    following = false;
    manual();
    yaw = pointer.angle - x * 0.006;
    pitch = T.MathUtils.clamp(pointer.pitch - y * 0.004, -0.95, 0.8);
    wake();
  };
  canvas.onpointerup = (e) => {
    if (pointer && !pointer.moved) {
      const r = canvas.getBoundingClientRect();
      ray.setFromCamera(
        new T.Vector2(
          ((e.clientX - r.left) / r.width) * 2 - 1,
          1 - ((e.clientY - r.top) / r.height) * 2,
        ),
        camera,
      );
      const hit = ray.intersectObjects([...racks, floor])[0];
      if (hit?.object === floor && active)
        directRaptor(hit.point.x, hit.point.z);
      const entry = hit && banks[hit.object.userData.bank];
      if (entry) inspect(entry.event.id);
    }
    pointer = null;
  };
  canvas.onpointercancel = () => {
    pointer = null;
  };
  canvas.onkeydown = (e) => {
    const k = e.key.toLowerCase();
    if (
      ![
        "w",
        "s",
        "a",
        "d",
        "arrowleft",
        "arrowright",
        "arrowup",
        "arrowdown",
      ].includes(k)
    )
      return;
    e.preventDefault();
    following = false;
    manual();
    keys.add(k);
    wake();
  };
  canvas.onkeyup = (e) => {
    keys.delete(e.key.toLowerCase());
  };
  canvas.onblur = () => keys.clear();
  motion.addEventListener("change", wake);
  return {
    update(
      items: (FrameEvent | undefined)[],
      selected: FrameEvent | undefined,
      alert: boolean,
      follow: boolean,
    ) {
      if (selected?.event.id !== packetId) {
        packetId = selected?.event.id;
        packetStarted = performance.now();
      }
      banks = items;
      const nextStation = selected?.station ?? 0;
      const changedBank =
        station !== nextStation || side !== (selected?.bank ?? 0) % 2;
      station = nextStation;
      side = (selected?.bank ?? 0) % 2;
      following = follow;
      if (alert && !active) guide?.appear(station, side);
      else if (alert && changedBank && guide) {
        guide.approachStation(station, side);
        if (!raptorMoves()) guide.model.position.copy(guide.destination);
      }
      active = alert;
      for (let i = 0; i < lamps.length; i++)
        lamps[i].color.set(
          !items[i]
            ? "#344740"
            : items[i]?.alert
              ? "#ff8866"
              : selected?.bank === i
                ? "#d8ffd6"
                : i % 2
                  ? "#c5a87d"
                  : "#6da88e",
        );
      if (alert) loadRaptor();
      wake();
    },
    allowRaptorMotion(value: boolean) {
      animateInReducedMotion = value;
      wake();
    },
    callRaptor() {
      directRaptor(
        camera.position.x - Math.sin(yaw) * 2.8,
        camera.position.z - Math.cos(yaw) * 2.8,
      );
    },
    flyForward() {
      following = false;
      manual();
      advance(1.4);
      wake();
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      ro.disconnect();
      motion.removeEventListener("change", wake);
      canvas.onpointerdown =
        canvas.onpointermove =
        canvas.onpointerup =
        canvas.onpointercancel =
          null;
      canvas.onkeydown = canvas.onkeyup = canvas.onblur = null;
      mixer?.stopAllAction();
      release(scene);
      renderer.dispose();
    },
  };
}
