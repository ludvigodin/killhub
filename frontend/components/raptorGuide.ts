import * as T from "three";

// The racks flank a straight central aisle. All destinations stay inside its
// clear strip, so a segment between any two destinations is also walkable.
export class RaptorGuide {
  readonly destination = new T.Vector3();
  private rest = 0;
  private speed = 0;
  private readonly idle: T.AnimationAction;
  private readonly stride: T.AnimationAction;
  readonly model: T.Group;
  private readonly mixer: T.AnimationMixer;
  constructor(
    model: T.Group,
    mixer: T.AnimationMixer,
    walk: T.AnimationClip,
    idle: T.AnimationClip,
  ) {
    this.model = model;
    this.mixer = mixer;
    this.stride = mixer.clipAction(walk);
    this.stride.setEffectiveWeight(0).play();
    this.idle = mixer.clipAction(idle).play();
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
    if (distance < 0.16) {
      this.rest += dt;
      this.speed = T.MathUtils.damp(this.speed, 0, 12, dt);
      if (this.rest >= 1.5) {
        // Pick a point in the operator's view with room for several full steps.
        const near = T.MathUtils.clamp(camera.z - 2.8, -16, 7);
        const far = near - 6.5;
        let z = T.MathUtils.lerp(far, near, Math.random());
        if (Math.abs(z - pos.z) < 2.25)
          z = pos.z < (far + near) / 2 ? near : far;
        this.goTo((Math.random() - 0.5) * 1.9, z);
      }
    } else {
      const desired = Math.atan2(dx, dz);
      const turn = Math.atan2(
        Math.sin(desired - this.model.rotation.y),
        Math.cos(desired - this.model.rotation.y),
      );
      this.model.rotation.y += T.MathUtils.clamp(turn, -dt * 3.2, dt * 3.2);
      const pace =
        Math.min(1.65, Math.sqrt(4 * distance)) * Math.max(0, Math.cos(turn));
      this.speed = T.MathUtils.damp(this.speed, pace, 7, dt);
      const travel = Math.min(distance, this.speed * dt);
      pos.x += (dx / distance) * travel;
      pos.z += (dz / distance) * travel;
    }

    // Idle and walk share a planted pose. Keep the mixer running through turns
    // and arrivals so the neck and tail remain alive while the feet settle.
    const walking = T.MathUtils.smoothstep(this.speed, 0.05, 0.65);
    this.idle.setEffectiveWeight(1 - walking);
    this.stride.setEffectiveWeight(walking);
    this.stride.timeScale = Math.max(0.4, this.speed / 1.65);
    this.mixer.update(dt);
  }
}
