# ecosimkit — cienki SDK realizujący kontrakt we/wy dla analiz Ecosim.
# Skrypt naukowca dostaje gotowe, przefiltrowane dane (sandbox) i zwraca artefakty
# do out/ wraz z wpisem w out/result.json. Patrz docs/data-contract.md.

.job_dir <- function() {
  d <- Sys.getenv("ECOSIM_JOB_DIR", unset = ".")
  normalizePath(d, mustWork = FALSE)
}

.out_dir <- function() {
  p <- file.path(.job_dir(), "out")
  dir.create(p, recursive = TRUE, showWarnings = FALSE)
  p
}

#' Wczytaj przefiltrowane szeregi czasowe (tidy) przygotowane przez framework.
ecosim_load_timeseries <- function() {
  path <- file.path(.job_dir(), "data", "timeseries.parquet")
  if (requireNamespace("arrow", quietly = TRUE)) {
    return(as.data.frame(arrow::read_parquet(path)))
  }
  csv <- sub("\\.parquet$", ".csv", path)
  if (file.exists(csv)) return(utils::read.csv(csv, check.names = FALSE))
  stop("Package 'arrow' is not installed and no CSV fallback exists at: ", path)
}

#' Wczytaj słownik: "groups" | "fleets" | "scenarios".
ecosim_dict <- function(name = c("groups", "fleets", "scenarios")) {
  name <- match.arg(name)
  utils::read.csv(file.path(.job_dir(), "data", "dictionaries", paste0(name, ".csv")),
                  check.names = FALSE)
}

#' Manifest selekcji z UI (lista).
ecosim_manifest <- function() {
  jsonlite::fromJSON(file.path(.job_dir(), "manifest.json"))
}

#' Parametry formularza analizy (lista).
ecosim_params <- function() {
  p <- file.path(.job_dir(), "params.json")
  if (file.exists(p)) jsonlite::fromJSON(p) else list()
}

# --- emitery: zapis artefaktu + wpis do result.json -------------------------

.result_path <- function() file.path(.out_dir(), "result.json")

.append_artifact <- function(artifact) {
  rp <- .result_path()
  res <- if (file.exists(rp)) jsonlite::fromJSON(rp, simplifyVector = FALSE)
         else list(status = "ok", artifacts = list())
  res$artifacts <- c(res$artifacts, list(artifact))
  jsonlite::write_json(res, rp, auto_unbox = TRUE, pretty = TRUE)
  invisible(artifact)
}

ecosim_emit_figure <- function(plot, filename, title = NULL, width = 8, height = 5, dpi = 120) {
  rel <- file.path("figures", filename)
  abs <- file.path(.out_dir(), rel)
  dir.create(dirname(abs), recursive = TRUE, showWarnings = FALSE)
  ggplot2::ggsave(abs, plot = plot, width = width, height = height, dpi = dpi)
  .append_artifact(list(type = "figure", path = rel, title = title))
}

ecosim_emit_table <- function(df, filename = "table.csv", title = NULL) {
  rel <- file.path("tables", filename)
  abs <- file.path(.out_dir(), rel)
  dir.create(dirname(abs), recursive = TRUE, showWarnings = FALSE)
  utils::write.csv(df, abs, row.names = FALSE)
  .append_artifact(list(type = "table", path = rel, title = title))
}

ecosim_emit_map <- function(src_tif, filename, title = NULL) {
  rel <- file.path("rasters", filename)
  abs <- file.path(.out_dir(), rel)
  dir.create(dirname(abs), recursive = TRUE, showWarnings = FALSE)
  file.copy(src_tif, abs, overwrite = TRUE)
  .append_artifact(list(type = "map", path = rel, title = title))
}

ecosim_emit_scalar <- function(value, title = NULL, unit = NULL) {
  .append_artifact(list(type = "scalar", value = value, title = title, unit = unit))
}
