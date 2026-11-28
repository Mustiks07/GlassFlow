// Set the fixture environment portably, including Windows cmd.exe package scripts.
process.env.VITE_GLASSFLOW_TRANSPORT = 'fixture';
const { build, createServer } = await import('vite');
if (process.argv[2] === 'build') {
  await build({ build: { outDir: 'dist-fixture' } });
} else {
  const server = await createServer({ server: { host: '127.0.0.1', port: 5174 } });
  await server.listen();
  server.printUrls();
}
