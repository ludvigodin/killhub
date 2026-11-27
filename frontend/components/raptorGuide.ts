import * as T from "three";

// The racks flank a straight central aisle. All destinations stay inside its
// clear strip, so a segment between any two destinations is also walkable.
export class RaptorGuide {
  readonly destination = new T.Vector3();
  private rest = 0;
  private speed = 0;
  private readonly stride: T.AnimationAction;
  constructor(
    readonly model: T.Group,
    private readonly mixer: T.AnimationMixer,
    walk: T.AnimationClip,
  ) {
    this.stride = mixer.clipAction(walk);
    this.stride.play();
  }
  goTo(x: number, z: number) {
    this.destination.set(
      T.MathUtils.clamp(x, -1.02, 1.02),
      0,
      T.MathUtils.clamp(z, -23, 7),
    );
    this.rest = 0;
  }
  approachStation(station: number, side: number) {
    this.goTo(side ? 0.65 : -0.65, 3.2 - station * 4.3);
  }
  appear(station: number, side: number) {
    this.model.position.set(-0.65, 0, 4.8 - station * 4.3);
    this.model.rotation.y = 2.15;
    this.speed = 0;
    this.approachStation(station, side);
  }
  step(dt: number, camera: T.Vector3) {
    const pos = this.model.position;
    const clearance = Math.hypot(camera.x - pos.x, camera.z - pos.z);
    if (
      clearance < 1.65 &&
      Math.hypot(this.destination.x - camera.x, this.destination.z - camera.z) <
        3
    ) {
      // Step away along the aisle when the operator approaches.
      this.goTo(
        camera.x > 0 ? -0.9 : 0.9,
        pos.z + (pos.z < camera.z ? -3.2 : 3.2),
      );
    }
    const dx = this.destination.x - pos.x,
      dz = this.destination.z - pos.z;
    const distance = Math.hypot(dx, dz);
    if (distance < 0.12) {
      this.speed = 0;
      this.rest += dt;
      if (this.rest > 2.8) {
        const z = T.MathUtils.clamp(
          camera.z - 4 + (Math.random() - 0.5) * 8,
          -22,
          6,
        );
        this.goTo((Math.random() - 0.5) * 1.85, z);
      }
      return;
    }
    const desired = Math.atan2(dx, dz);
    const turn = Math.atan2(
      Math.sin(desired - this.model.rotation.y),
      Math.cos(desired - this.model.rotation.y),
    );
    this.model.rotation.y += T.MathUtils.clamp(turn, -dt * 2.8, dt * 2.8);
    const speed = Math.min(1.55, distance * 2) * Math.max(0, Math.cos(turn));
    this.speed = T.MathUtils.damp(this.speed, speed, 6, dt);
    const travel = Math.min(distance, this.speed * dt);
    pos.x += (dx / distance) * travel;
    pos.z += (dz / distance) * travel;
    this.stride.timeScale = this.speed / 1.55;
    this.mixer.update(dt);
  }
}
