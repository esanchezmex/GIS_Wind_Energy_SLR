import geopandas as gpd
import pandas as pd

shp_path = "raw_data/EMODnet_HA_Energy_WindFarms_20260127/EMODnet_HA_Energy_WindFarms_pt_20260127.shp"
csv_path = "raw_data/EMODnet_HA_Energy_WindFarms_20260127/EMODnet_HA_Energy_WindFarms_pt_20260127.csv"

gdf = gpd.read_file(shp_path)

# CSV in your repo is semicolon-delimited and BOM-prefixed
df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig", decimal=",")

# Option A: if COUNTRY already exists in shapefile
uk = gdf[gdf["COUNTRY"] == "United Kingdom"]

uk.to_file("processed_data/offshore_windfarms_uk.gpkg", driver="GPKG")