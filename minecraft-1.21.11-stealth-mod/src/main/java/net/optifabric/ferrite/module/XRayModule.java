package net.optifabric.ferrite.module;

import it.unimi.dsi.fastutil.objects.ReferenceOpenHashSet;
import java.util.Set;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.renderer.blockentity.state.BlockEntityRenderState;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.entity.vehicle.minecart.AbstractMinecart;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.ShulkerBoxBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.optifabric.ferrite.bridge.OptionInstanceDuck;

public final class XRayModule {
	public static final XRayModule INSTANCE = new XRayModule();

	/**
	 * Zero-allocation O(1) identity set of core valuable blocks (Ores, Containers, Spawners, Portals).
	 * Eliminates String/Identifier allocations during chunk meshing so flying at 60 BPS with X-Ray has zero lag.
	 */
	private static final Set<Block> CORE_VALUABLE_BLOCKS = new ReferenceOpenHashSet<>(new Block[] {
		// Diamond & Netherite
		Blocks.DIAMOND_ORE,
		Blocks.DEEPSLATE_DIAMOND_ORE,
		Blocks.DIAMOND_BLOCK,
		Blocks.ANCIENT_DEBRIS,
		Blocks.NETHERITE_BLOCK,
		// Emerald
		Blocks.EMERALD_ORE,
		Blocks.DEEPSLATE_EMERALD_ORE,
		Blocks.EMERALD_BLOCK,
		// Gold
		Blocks.GOLD_ORE,
		Blocks.DEEPSLATE_GOLD_ORE,
		Blocks.NETHER_GOLD_ORE,
		Blocks.GILDED_BLACKSTONE,
		Blocks.RAW_GOLD_BLOCK,
		Blocks.GOLD_BLOCK,
		// Iron
		Blocks.IRON_ORE,
		Blocks.DEEPSLATE_IRON_ORE,
		Blocks.RAW_IRON_BLOCK,
		Blocks.IRON_BLOCK,
		// Lapis & Redstone
		Blocks.LAPIS_ORE,
		Blocks.DEEPSLATE_LAPIS_ORE,
		Blocks.LAPIS_BLOCK,
		Blocks.REDSTONE_ORE,
		Blocks.DEEPSLATE_REDSTONE_ORE,
		Blocks.REDSTONE_BLOCK,
		// Coal, Copper & Quartz
		Blocks.COAL_ORE,
		Blocks.DEEPSLATE_COAL_ORE,
		Blocks.COAL_BLOCK,
		Blocks.COPPER_ORE,
		Blocks.DEEPSLATE_COPPER_ORE,
		Blocks.RAW_COPPER_BLOCK,
		Blocks.NETHER_QUARTZ_ORE,
		// Containers, Stashes & Redstone Base Mechanisms
		Blocks.CHEST,
		Blocks.TRAPPED_CHEST,
		Blocks.ENDER_CHEST,
		Blocks.BARREL,
		Blocks.HOPPER,
		Blocks.DISPENSER,
		Blocks.DROPPER,
		Blocks.FURNACE,
		Blocks.BLAST_FURNACE,
		Blocks.SMOKER,
		Blocks.BREWING_STAND,
		Blocks.CRAFTER,
		Blocks.ANVIL,
		Blocks.CHIPPED_ANVIL,
		Blocks.DAMAGED_ANVIL,
		Blocks.ENCHANTING_TABLE,
		Blocks.BOOKSHELF,
		Blocks.CHISELED_BOOKSHELF,
		Blocks.DECORATED_POT,
		Blocks.REDSTONE_TORCH,
		Blocks.REDSTONE_WALL_TORCH,
		Blocks.REPEATER,
		Blocks.COMPARATOR,
		Blocks.OBSERVER,
		Blocks.PISTON,
		Blocks.STICKY_PISTON,
		// Spawners, Trial Chambers (1.21.11), Pale Garden, Deep Dark & Portals
		Blocks.SPAWNER,
		Blocks.MOSSY_COBBLESTONE,
		Blocks.TRIAL_SPAWNER,
		Blocks.VAULT,
		Blocks.HEAVY_CORE,
		Blocks.CREAKING_HEART,
		Blocks.BEACON,
		Blocks.CONDUIT,
		Blocks.END_PORTAL_FRAME,
		Blocks.END_PORTAL,
		Blocks.NETHER_PORTAL,
		Blocks.DRAGON_EGG,
		Blocks.RESPAWN_ANCHOR,
		Blocks.LODESTONE,
		Blocks.AMETHYST_CLUSTER,
		Blocks.BUDDING_AMETHYST,
		Blocks.SCULK_CATALYST,
		Blocks.SCULK_SHRIEKER,
		Blocks.REINFORCED_DEEPSLATE,
		Blocks.SUSPICIOUS_SAND,
		Blocks.SUSPICIOUS_GRAVEL,
		Blocks.NETHER_WART,
		Blocks.OBSIDIAN,
		Blocks.CRYING_OBSIDIAN,
		Blocks.TNT
	});

	/**
	 * Fluid blocks (Lava, Water, Bubble Column) shown when the Mobs + Lava + Water option is active.
	 */
	private static final Set<Block> FLUID_BLOCKS = new ReferenceOpenHashSet<>(new Block[] {
		Blocks.LAVA,
		Blocks.WATER,
		Blocks.BUBBLE_COLUMN
	});

	private final ThreadLocal<BlockPos.MutableBlockPos> mutablePos =
		ThreadLocal.withInitial(BlockPos.MutableBlockPos::new);

	private volatile boolean enabled = false;
	/**
	 * Option requested by user: when enabled (default = true, toggleable via B or Alt + X),
	 * Mobs, Lava, and Water are also rendered alongside main ores & chests.
	 */
	private volatile boolean showMobsAndFluids = true;
	private volatile boolean exposedOnlyBypass = false;
	private double savedGamma = 1.0;

	private XRayModule() {}

	public boolean isEnabled() {
		return enabled;
	}

	public boolean isShowMobsAndFluids() {
		return showMobsAndFluids;
	}

	public boolean isExposedOnlyBypass() {
		return exposedOnlyBypass;
	}

	public void toggle() {
		setEnabled(!enabled);
	}

	public void toggleShowMobsAndFluids() {
		showMobsAndFluids = !showMobsAndFluids;
		if (enabled) {
			reloadChunks();
		}
	}

	public void toggleExposedOnlyBypass() {
		exposedOnlyBypass = !exposedOnlyBypass;
		if (enabled) {
			reloadChunks();
		}
	}

	public void setEnabled(boolean state) {
		if (this.enabled == state) {
			return;
		}
		this.enabled = state;
		Minecraft mc = Minecraft.getInstance();
		if (mc.options != null) {
			if (state) {
				double current = mc.options.gamma().get();
				if (current <= 1.0) {
					savedGamma = current;
				}
				OptionInstanceDuck.of(mc.options.gamma()).setUncheckedValue(16.0);
			} else {
				OptionInstanceDuck.of(mc.options.gamma()).setUncheckedValue(savedGamma);
			}
		}
		reloadChunks();
	}

	public void onTick() {
		if (!enabled) {
			return;
		}
		Minecraft mc = Minecraft.getInstance();
		if (mc.options != null && mc.options.gamma().get() < 16.0) {
			OptionInstanceDuck.of(mc.options.gamma()).setUncheckedValue(16.0);
		}
	}

	public Boolean shouldDrawSide(BlockState state, BlockPos pos) {
		if (!enabled || state == null) {
			return null;
		}
		return isVisible(state.getBlock(), pos);
	}

	public boolean shouldHideBlockEntity(BlockEntityRenderState renderState) {
		if (!enabled) {
			return false;
		}
		ClientLevel level = Minecraft.getInstance().level;
		if (level == null || renderState == null || renderState.blockPos == null) {
			return false;
		}
		BlockPos pos = renderState.blockPos;
		Block block = level.getBlockState(pos).getBlock();
		return !isVisible(block, pos);
	}

	public boolean isVisible(Block block, BlockPos pos) {
		if (block == null) {
			return false;
		}
		if (FLUID_BLOCKS.contains(block)) {
			return showMobsAndFluids;
		}
		boolean isValuable = CORE_VALUABLE_BLOCKS.contains(block) || block instanceof ShulkerBoxBlock;
		if (!isValuable) {
			return false;
		}
		if (exposedOnlyBypass && pos != null) {
			return isExposedToCaveOrFluid(pos);
		}
		return true;
	}

	/**
	 * Determines whether an Entity (Mob, Player, Animal, Minecart, Item) should be highlighted
	 * through walls when X-Ray and the Mobs+Lava+Water option are active.
	 */
	public boolean shouldHighlightEntity(Entity entity) {
		if (!enabled || !showMobsAndFluids || entity == null) {
			return false;
		}
		Minecraft mc = Minecraft.getInstance();
		if (entity == mc.player || entity.isRemoved()) {
			return false;
		}
		return entity instanceof LivingEntity
			|| entity instanceof AbstractMinecart
			|| entity instanceof ItemEntity;
	}

	/**
	 * Returns color-coded RGB outline color for entities when X-Ray Mobs mode is active:
	 * - Hostile Mobs (Creeper, Zombie, Warden, Skeleton, etc.): Red-Orange (0xFF3B30)
	 * - Players / Spectating Admins: Cyan (0x00F5D4)
	 * - Passive Mobs / Animals / Villagers: Bright Green (0x34C759)
	 * - Chest Minecarts / Dropped Items: Gold (0xFFD60A)
	 */
	public int getEntityOutlineColor(Entity entity) {
		if (entity instanceof Player) {
			return 0x00F5D4;
		}
		if (entity instanceof Enemy) {
			return 0xFF3B30;
		}
		if (entity instanceof LivingEntity) {
			return 0x34C759;
		}
		return 0xFFD60A;
	}

	private boolean isExposedToCaveOrFluid(BlockPos pos) {
		try {
			ClientLevel level = Minecraft.getInstance().level;
			if (level == null) {
				return true;
			}
			BlockPos.MutableBlockPos neighbor = mutablePos.get();
			for (Direction dir : Direction.values()) {
				neighbor.setWithOffset(pos, dir);
				if (!level.getBlockState(neighbor).isSolidRender()) {
					return true;
				}
			}
			return false;
		} catch (Throwable ignored) {
			return true;
		}
	}

	private void reloadChunks() {
		Minecraft mc = Minecraft.getInstance();
		if (mc.levelRenderer != null) {
			mc.levelRenderer.allChanged();
		}
	}
}
