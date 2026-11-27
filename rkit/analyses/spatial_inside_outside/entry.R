# Inside vs outside: the map variable inside each area of interest against the
# rest of the model's grid, year by year. Area-weighted means (plan 27.08,
# section 1.3), from data/zonal.parquet (side = inside / outside).

source(Sys.getenv("ECOSIM_KIT_PATH"))
suppressMessages(library(dplyr))
suppressMessages(library(ggplot2))

z <- ecosim_load_zonal()
names_by_area <- z %>% filter(side == "inside") %>% distinct(area, area_name)
z <- z %>%
  select(area, side, entity, year, mean) %>%
  left_join(names_by_area, by = "area") %>%
  mutate(series = if_else(is.na(entity) | entity == "", area_name, paste(area_name, entity, sep = " · ")))

fig <- ggplot(z, aes(year, mean, colour = side)) +
  geom_line(linewidth = 0.8) + geom_point(size = 1.2) +
  facet_wrap(~ series, scales = "free_y") +
  scale_colour_manual(values = c(inside = "#eb6834", outside = "#55606e")) +
  labs(x = "Year", y = "Area-weighted mean", colour = NULL) +
  theme_minimal() + theme(legend.position = "bottom")
ecosim_emit_figure(fig, "inside_outside.png", title = "Inside vs outside each area")

paired <- inner_join(
  z %>% filter(side == "inside") %>% select(series, year, inside = mean),
  z %>% filter(side == "outside") %>% select(series, year, outside = mean),
  by = c("series", "year")
) %>% filter(!is.na(inside), !is.na(outside))

stats <- paired %>%
  group_by(series) %>%
  summarise(
    years = n(),
    mean_inside = mean(inside),
    mean_outside = mean(outside),
    ratio = mean_inside / mean_outside,
    mean_difference = mean(inside - outside),
    paired_t_p = if (n() >= 3 && sd(inside - outside) > 0) t.test(inside, outside, paired = TRUE)$p.value else NA_real_,
    .groups = "drop"
  )
ecosim_emit_table(stats, "inside_outside.csv", title = "Inside vs outside: paired over the years")
