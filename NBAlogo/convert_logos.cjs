const sharp = require("C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/sharp");
const fs = require("fs");
const path = require("path");

const SRC = "C:/autopick/AutoPick/nba_data/NBAlogo";
const OUT = path.join(SRC, "png");
fs.mkdirSync(OUT, { recursive: true });

const logos = ["nba", "lal", "okc", "mil", "den", "bos", "cle", "hou", "min", "orl"];

async function convertAll() {
  for (const name of logos) {
    const svg = path.join(SRC, `${name}.svg`);
    const png = path.join(OUT, `${name}.png`);
    try {
      await sharp(svg).resize(200, 200).png().toFile(png);
      const kb = (fs.statSync(png).size / 1024).toFixed(1);
      console.log(`OK  ${name}.svg → ${name}.png (${kb} KB)`);
    } catch (e) {
      console.log(`ERR ${name}.svg: ${e.message}`);
    }
  }
  console.log(`\nDone! Output: ${OUT}`);
}

convertAll();
