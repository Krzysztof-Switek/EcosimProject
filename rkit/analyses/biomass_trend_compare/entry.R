# Example analysis: biomass trend comparison across scenarios.
# Demonstrates the contract: load data + params, emit a figure/table/scalar.

`%||%` <- function(a, b) if (is.null(a)) b else a

source(Sys.getenv("ECOSIM_KIT_PATH"))
suppressMessages(library(dplyr))
suppressMessages(library(ggplot2))

ts     <- ecosim_load_timeseries()
params <- ecosim_params()
smooth <- as.numeric(params$smoothing %||% 3)
relative <- isTRUE(params$relative)

df <- ts %>%
  filter(variable == "biomass", freq == "annual", !is.na(group_name)) %>%
  arrange(scenario, group_name, year)

if (nrow(df) == 0) {
  stop("No biomass data matched the selected scenarios/groups/years.")
}

df <- df %>%
  group_by(scenario, group_name) %>%
  mutate(value_s = stats::filter(value, rep(1 / smooth, smooth), sides = 2) %>% as.numeric()) %>%
  ungroup()

if (relative) {
  df <- df %>%
    group_by(scenario, group_name) %>%
    mutate(value_s = value_s / first(na.omit(value_s)) * 100) %>%
    ungroup()
}

fig <- ggplot(df, aes(year, value_s, colour = scenario)) +
  geom_line(linewidth = 0.8) +
  facet_wrap(~ group_name, scales = "free_y") +
  labs(x = "Year", y = if (relative) "Biomass (% of base year)" else "Biomass",
       colour = "Scenario") +
  theme_minimal()

ecosim_emit_figure(fig, "biomass_trend.png", title = "Biomass trend comparison")

summary_tbl <- df %>%
  group_by(scenario, group_name) %>%
  summarise(start = first(na.omit(value)), end = last(na.omit(value)),
            change_pct = (end - start) / start * 100, .groups = "drop")

ecosim_emit_table(summary_tbl, "summary.csv", title = "Biomass change: first -> last year")
