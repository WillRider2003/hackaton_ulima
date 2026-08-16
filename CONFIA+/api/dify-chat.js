// Proxy serverless (Vercel) hacia la API de chat de Dify.
// Corre en el servidor, así que la clave secreta NUNCA se expone en el navegador
// y evitamos cualquier problema de CORS al llamar a la API desde la página de la llamada.
//
// Si prefieres no dejar la clave escrita aquí, puedes definir en Vercel
// (Project Settings -> Environment Variables) las variables DIFY_API_KEY y
// DIFY_BASE_URL; si no existen, se usan los valores por defecto de abajo.

const DIFY_API_KEY_DEFAULT = 'app-9xlo8bt4D4R1jPqiL9MDIcDj';
const DIFY_BASE_URL_DEFAULT = 'https://api.dify.ai/v1';

module.exports = async (req, res) => {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'Método no permitido. Usa POST.' });
    return;
  }

  try {
    const body = req.body || {};
    const query = (body.query || '').toString().trim();
    const conversationId = body.conversation_id || '';

    if (!query) {
      res.status(400).json({ error: 'Falta el campo "query".' });
      return;
    }

    const apiKey = process.env.DIFY_API_KEY || DIFY_API_KEY_DEFAULT;
    const baseUrl = process.env.DIFY_BASE_URL || DIFY_BASE_URL_DEFAULT;

    const difyResponse = await fetch(`${baseUrl}/chat-messages`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        inputs: {},
        query,
        response_mode: 'blocking',
        conversation_id: conversationId,
        user: 'demo-llamada-confia',
      }),
    });

    const data = await difyResponse.json();

    if (!difyResponse.ok) {
      res.status(difyResponse.status).json({
        error: data.message || 'Dify devolvió un error.',
        detail: data,
      });
      return;
    }

    res.status(200).json({
      answer: data.answer,
      conversation_id: data.conversation_id,
    });
  } catch (err) {
    res.status(500).json({ error: 'Error interno del proxy.', detail: String(err) });
  }
};
