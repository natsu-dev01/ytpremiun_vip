#!/usr/bin/env node
/**
 * Punto de entrada del CLI nativo de ytpremiun-vip.
 *
 * No necesita Python: todo el motor está implementado en JavaScript dentro de
 * `lib/`. Se expone como `ytpremiun-vip` al instalar el paquete npm.
 */

"use strict";

const { main } = require("../lib/cli");

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error) => {
    process.stderr.write(`ERROR: ${error?.stack || error}\n`);
    process.exitCode = 1;
  });
