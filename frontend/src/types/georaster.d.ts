declare module "georaster" {
  import type { GeoRaster } from "georaster-layer-for-leaflet";

  export default function parseGeoraster(input: ArrayBuffer | string): Promise<GeoRaster>;
}
