// Configuração mínima do Node-RED para o CardioIA Fase 3.
// Rodar a partir desta pasta: npm install && npm start
module.exports = {
    uiPort: process.env.PORT || 1880,
    flowFile: "flows.json",
    flowFilePretty: true,
    // Sem credenciais no flow (broker público), então não há segredo a cifrar
    credentialSecret: false,
    editorTheme: { projects: { enabled: false }, tours: false },
    // Não pergunta sobre telemetria ao abrir o editor
    telemetry: { enabled: false },
    logging: { console: { level: "info", metrics: false, audit: false } },
    functionGlobalContext: {},
    exportGlobalContextKeys: false
};
