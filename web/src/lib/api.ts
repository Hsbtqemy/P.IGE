// Thin client for the P.IGE server API (same origin).

/** Thrown for HTTP errors; `status` 0 means the network was unreachable. */
export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	let response: Response;
	try {
		response = await fetch(path, {
			method,
			credentials: 'same-origin',
			headers: {
				// Required by the server on cookie-authenticated writes (CSRF guard).
				'x-pige-client': 'web',
				...(body === undefined ? {} : { 'content-type': 'application/json' })
			},
			body: body === undefined ? undefined : JSON.stringify(body)
		});
	} catch {
		throw new ApiError(0, 'Hors connexion');
	}
	if (!response.ok) {
		let detail = response.statusText;
		try {
			const data = await response.json();
			if (typeof data.detail === 'string') detail = data.detail;
		} catch {
			/* not JSON */
		}
		throw new ApiError(response.status, detail);
	}
	if (response.status === 204) return undefined as T;
	return (await response.json()) as T;
}

export const api = {
	session: () => request<{ authenticated: boolean }>('GET', '/api/session'),
	login: (password: string) => request<{ authenticated: boolean }>('POST', '/api/login', { password }),
	logout: () => request<{ authenticated: boolean }>('POST', '/api/logout')
};

/** 32 lowercase hex characters, the id format the server expects. */
export function newId(): string {
	return crypto.randomUUID().replaceAll('-', '');
}
