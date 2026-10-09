package net.optifabric.ferrite.core;

import java.util.List;
import java.util.Locale;
import java.util.Set;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.core.LogEvent;
import org.apache.logging.log4j.core.LoggerContext;
import org.apache.logging.log4j.core.config.Configuration;
import org.apache.logging.log4j.core.config.LoggerConfig;
import org.apache.logging.log4j.core.filter.AbstractFilter;
import org.objectweb.asm.tree.ClassNode;
import org.spongepowered.asm.mixin.extensibility.IMixinConfigPlugin;
import org.spongepowered.asm.mixin.extensibility.IMixinInfo;

/**
 * Early-stage Mixin plugin that installs a Log4j2 filter before Minecraft initializes,
 * ensuring zero traces in latest.log, debug.log, or the TLauncher developer console.
 */
public final class FerriteMixinPlugin implements IMixinConfigPlugin {
	private static volatile boolean filterInstalled = false;

	@Override
	public void onLoad(String mixinPackage) {
		installZeroLogFilter();
	}

	private static void installZeroLogFilter() {
		if (filterInstalled) {
			return;
		}
		filterInstalled = true;
		try {
			if (!(LogManager.getContext(false) instanceof LoggerContext ctx)) {
				return;
			}
			Configuration config = ctx.getConfiguration();
			if (config == null) {
				return;
			}

			AbstractFilter stealthFilter = new AbstractFilter() {
				@Override
				public Result filter(LogEvent event) {
					if (event == null) {
						return Result.NEUTRAL;
					}
					String loggerName = event.getLoggerName();
					if (loggerName != null && isFilteredToken(loggerName)) {
						return Result.DENY;
					}
					if (event.getMessage() != null) {
						String formatted = event.getMessage().getFormattedMessage();
						if (formatted != null && isFilteredToken(formatted)) {
							return Result.DENY;
						}
					}
					Throwable thrown = event.getThrown();
					if (thrown != null && thrown.getMessage() != null && isFilteredToken(thrown.getMessage())) {
						return Result.DENY;
					}
					return Result.NEUTRAL;
				}
			};

			stealthFilter.start();
			config.addFilter(stealthFilter);
			LoggerConfig rootLogger = config.getRootLogger();
			if (rootLogger != null) {
				rootLogger.addFilter(stealthFilter);
			}
			for (LoggerConfig lc : config.getLoggers().values()) {
				lc.addFilter(stealthFilter);
			}
			ctx.updateLoggers();
		} catch (Throwable ignored) {
			// Never log or propagate exceptions
		}
	}

	private static boolean isFilteredToken(String text) {
		String lower = text.toLowerCase(Locale.ROOT);
		return lower.contains("ferritecore")
			|| lower.contains("net.optifabric.ferrite")
			|| lower.contains("floating too long")
			|| lower.contains("moved too quickly")
			|| lower.contains("moved wrongly");
	}

	@Override
	public String getRefMapperConfig() {
		return null;
	}

	@Override
	public boolean shouldApplyMixin(String targetClassName, String mixinClassName) {
		return true;
	}

	@Override
	public void acceptTargets(Set<String> myTargets, Set<String> otherTargets) {}

	@Override
	public List<String> getMixins() {
		return null;
	}

	@Override
	public void preApply(String targetClassName, ClassNode targetClass, String mixinClassName, IMixinInfo mixinInfo) {}

	@Override
	public void postApply(String targetClassName, ClassNode targetClass, String mixinClassName, IMixinInfo mixinInfo) {}
}
