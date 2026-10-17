package net.optifabric.ferrite.mixin;

import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.llamalad7.mixinextras.injector.wrapoperation.WrapOperation;
import com.mojang.authlib.GameProfile;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.AbstractClientPlayer;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.phys.Vec3;
import net.optifabric.ferrite.core.StealthController;
import net.optifabric.ferrite.module.AutoClickerModule;
import net.optifabric.ferrite.module.FlightModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(LocalPlayer.class)
public abstract class LocalPlayerMixin extends AbstractClientPlayer {
	private LocalPlayerMixin(ClientLevel level, GameProfile profile) {
		super(level, profile);
	}

	@Inject(
		method = "tick()V",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/player/AbstractClientPlayer;tick()V",
			ordinal = 0
		)
	)
	private void onTick(CallbackInfo ci) {
		StealthController.INSTANCE.onClientTick((LocalPlayer) (Object) this);
	}

	@Inject(
		method = "aiStep()V",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/player/AbstractClientPlayer;aiStep()V",
			ordinal = 0
		)
	)
	private void onPreAiStepTravel(CallbackInfo ci) {
		FlightModule.INSTANCE.onPreTravel((LocalPlayer) (Object) this);
	}

	@Inject(method = "aiStep()V", at = @At("TAIL"))
	private void onPostAiStepTravel(CallbackInfo ci) {
		FlightModule.INSTANCE.onPostTravel((LocalPlayer) (Object) this);
	}

	@Inject(method = "sendPosition()V", at = @At("HEAD"))
	private void onPreSendPosition(CallbackInfo ci) {
		FlightModule.INSTANCE.onPreSendPosition((LocalPlayer) (Object) this);
	}

	@Inject(method = "sendPosition()V", at = @At("TAIL"))
	private void onPostSendPosition(CallbackInfo ci) {
		FlightModule.INSTANCE.onPostSendPosition((LocalPlayer) (Object) this);
	}

	@WrapOperation(
		method = "aiStep()V",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/player/LocalPlayer;isSlowDueToUsingItem()Z",
			ordinal = 0
		)
	)
	private boolean onAiStepSlowCheck(LocalPlayer instance, Operation<Boolean> original) {
		if (FlightModule.INSTANCE.isEnabled()) {
			return false;
		}
		return original.call(instance);
	}

	@WrapOperation(
		method = "modifyInput(Lnet/minecraft/world/phys/Vec2;)Lnet/minecraft/world/phys/Vec2;",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/player/LocalPlayer;isUsingItem()Z",
			ordinal = 0
		)
	)
	private boolean onModifyInputSlowCheck(LocalPlayer instance, Operation<Boolean> original) {
		if (FlightModule.INSTANCE.isEnabled()) {
			return false;
		}
		return original.call(instance);
	}

	@Override
	public void lerpMotion(Vec3 vec) {
		if (FlightModule.INSTANCE.isEnabled()) {
			FlightModule.INSTANCE.onServerVelocity(vec);
			return;
		}
		if (AutoClickerModule.INSTANCE.isEnabled() && vec != null) {
			// Legit Sprint-Hit Velocity Dampening (within Vanilla 0.6x attack slowdown bounds)
			super.lerpMotion(new Vec3(vec.x * 0.76D, vec.y, vec.z * 0.76D));
			return;
		}
		super.lerpMotion(vec);
	}

	@Override
	public boolean canGlide() {
		return !FlightModule.INSTANCE.isEnabled() && super.canGlide();
	}

	@Override
	public boolean isFallFlying() {
		return !FlightModule.INSTANCE.isEnabled() && super.isFallFlying();
	}
}
