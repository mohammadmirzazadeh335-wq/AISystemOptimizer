package net.optifabric.ferrite.mixin;

import net.minecraft.client.Camera;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.material.FogType;
import net.minecraft.world.phys.Vec3;
import net.optifabric.ferrite.module.FlightModule;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(Camera.class)
public abstract class CameraMixin {
	@Shadow
	private Vec3 position;

	@Shadow
	protected abstract void setPosition(Vec3 pos);

	@Inject(
		method = "setup(Lnet/minecraft/world/level/Level;Lnet/minecraft/world/entity/Entity;ZZF)V",
		at = @At("RETURN"),
		require = 0
	)
	private void onSetupCamera(
		Level level,
		Entity entity,
		boolean detached,
		boolean thirdPersonReverse,
		float partialTick,
		CallbackInfo ci
	) {
		if (!FlightModule.INSTANCE.isEnabled() || position == null || entity == null) {
			return;
		}
		double stabilizedY = FlightModule.INSTANCE.getStabilizedCameraY(entity, position.y);
		if (stabilizedY != position.y) {
			setPosition(new Vec3(position.x, stabilizedY, position.z));
		}
	}

	@Inject(
		method = "getFluidInCamera()Lnet/minecraft/world/level/material/FogType;",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onGetFluidInCamera(CallbackInfoReturnable<FogType> cir) {
		if (XRayModule.INSTANCE.isEnabled()) {
			cir.setReturnValue(FogType.NONE);
		}
	}
}
