declare module "shpjs" {
  function getShapefile(
    input: ArrayBuffer | string,
  ): Promise<GeoJSON.FeatureCollection | GeoJSON.FeatureCollection[]>;
  export default getShapefile;
}
