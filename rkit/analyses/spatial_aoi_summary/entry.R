# Area summary and trend: the map variable per area of interest and year.
# Data: data/zonal.parquet, computed by the framework (area-weighted mean over
# the area's cells that have a value; total = sum of value x cell area, only
# for densities such as biomass, catch, effort).

`%||%` <- function(a, b) if (is.null(a)) b else a

source(Sys.getenv("ECOSIM_KIT_PATH"))
suppressMessages(library(dplyr))
suppressMessages(library(ggplot2))

z <- ecosim_load_zonal()
params <- ecosim_params()
stat <- params$statistic %||% "mean"
if (!stat %in% c("mean", "total")) stop("Statistic must be 'mean' or 'total'.")
if (stat == "total" && !"total" %in% names(z)) {
  stop("A total isn't meaningful for this variable (not a density) -- use 'mean'.")
}

z <- z %>%
  filter(side == "inside") %>%
  mutate(series = if_else(is.na(entity) | entity == "", area_name, paste(area_name, entity, sep = " · ")),
         value = .data[[stat]])
band <- paste0(stat, "_p05") %in% names(z) && any(!is.na(z[[paste0(stat, "_p05")]]))

ylab <- paste0(z$variable[1], if (stat == "mean") " (area-weighted mean)" else " (total over the area)")
fig <- ggplot(z, aes(year, value, colour = series, fill = series))
if (band) {
  fig <- fig + geom_ribbon(aes(ymin = .data[[paste0(stat, "_p05")]], ymax = .data[[paste0(stat, "_p95")]]),
                           alpha = 0.15, colour = NA)
}
fig <- fig + geom_line(linewidth = 0.8) + geom_point(size = 1.2) +
  labs(x = "Year", y = ylab, colour = NULL, fill = NULL,
       caption = if (band) "Band: 5th-95th percentile over the Monte Carlo samples" else NULL) +
  theme_minimal() + theme(legend.position = "bottom")
ecosim_emit_figure(fig, "area_summary.png", title = paste("Per area:", z$variable[1]))

trend <- z %>%
  filter(!is.na(value)) %>%
  group_by(area_name, entity) %>%
  arrange(year, .by_group = TRUE) %>%
  summarise(
    years = paste(min(year), max(year), sep = "-"),
    first = first(value),
    last = last(value),
    change_pct = if_else(first != 0, (last - first) / abs(first) * 100, NA_real_),
    period_mean = mean(value),
    slope_per_year = if (n() >= 3) unname(coef(lm(value ~ year))[2]) else NA_real_,
    slope_p = if (n() >= 3) summary(lm(value ~ year))$coefficients[2, 4] else NA_real_,
    coverage = round(mean(coverage, na.rm = TRUE), 3),
    .groups = "drop"
  )
ecosim_emit_table(trend, "area_trend.csv", title = "Change and linear trend per area")
