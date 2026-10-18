// Passkeys (WebAuthn) in the browser: the server sends options as JSON, the device
// signs with a key that never leaves it, the answer goes back as JSON.

import { request } from '../api.js';

export interface DevicePasskey {
	id: string;
	name: string;
	created_at: number;
	last_used: number | null;
	synced: boolean;
}

export interface DeviceSession {
	id: string;
	label: string;
	method: 'password' | 'passkey';
	created_at: number;
	last_seen: number;
	current: boolean;
}

export interface Devices {
	passkeys_configured: boolean;
	passkeys: DevicePasskey[];
	sessions: DeviceSession[];
}

export const security = {
	status: () => request<{ configured: boolean; registered: boolean }>('GET', '/api/passkeys/status'),
	devices: () => request<Devices>('GET', '/api/devices'),
	renamePasskey: (id: string, name: string) => request('PATCH', `/api/passkeys/${encodeURIComponent(id)}`, { name }),
	removePasskey: (id: string) => request<void>('DELETE', `/api/passkeys/${encodeURIComponent(id)}`),
	endSession: (id: string) => request<void>('DELETE', `/api/sessions/${encodeURIComponent(id)}`),
	endOthers: () => request<{ ended: number }>('POST', '/api/sessions/end-others')
};

export function passkeysSupported(): boolean {
	return typeof window !== 'undefined' && typeof window.PublicKeyCredential === 'function' && !!navigator.credentials;
}

function fromB64u(text: string): ArrayBuffer {
	const b64 = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
	const raw = atob(b64);
	const bytes = new Uint8Array(raw.length);
	for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
	return bytes.buffer;
}

function toB64u(buffer: ArrayBuffer | null): string | null {
	if (!buffer) return null;
	let raw = '';
	for (const byte of new Uint8Array(buffer)) raw += String.fromCharCode(byte);
	return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

interface Descriptor {
	id: string;
	type: 'public-key';
	transports?: AuthenticatorTransport[];
}

function descriptors(list: Descriptor[] | undefined): PublicKeyCredentialDescriptor[] | undefined {
	return list?.map((d) => ({ ...d, id: fromB64u(d.id) }));
}

/** Create a passkey on this device and register it. */
export async function addPasskey(name: string): Promise<{ id: string; name: string }> {
	const options = await request<Record<string, unknown> & { challenge: string; user: { id: string; name: string; displayName: string }; excludeCredentials?: Descriptor[] }>(
		'POST',
		'/api/passkeys/register/options'
	);
	const credential = (await navigator.credentials.create({
		publicKey: {
			...(options as unknown as PublicKeyCredentialCreationOptions),
			challenge: fromB64u(options.challenge),
			user: { ...options.user, id: fromB64u(options.user.id) },
			excludeCredentials: descriptors(options.excludeCredentials)
		}
	})) as PublicKeyCredential | null;
	if (!credential) throw new Error('Création annulée');
	const response = credential.response as AuthenticatorAttestationResponse;
	return request('POST', '/api/passkeys/register/verify', {
		name,
		credential: {
			id: credential.id,
			rawId: toB64u(credential.rawId),
			type: credential.type,
			response: {
				clientDataJSON: toB64u(response.clientDataJSON),
				attestationObject: toB64u(response.attestationObject),
				transports: typeof response.getTransports === 'function' ? response.getTransports() : []
			},
			clientExtensionResults: credential.getClientExtensionResults(),
			authenticatorAttachment: credential.authenticatorAttachment ?? null
		}
	});
}

/** Sign in with a passkey of this device (or a phone nearby). */
export async function signInWithPasskey(): Promise<void> {
	const options = await request<Record<string, unknown> & { challenge: string; allowCredentials?: Descriptor[] }>(
		'POST',
		'/api/passkeys/login/options'
	);
	const credential = (await navigator.credentials.get({
		publicKey: {
			...(options as unknown as PublicKeyCredentialRequestOptions),
			challenge: fromB64u(options.challenge),
			allowCredentials: descriptors(options.allowCredentials)
		}
	})) as PublicKeyCredential | null;
	if (!credential) throw new Error('Connexion annulée');
	const response = credential.response as AuthenticatorAssertionResponse;
	await request('POST', '/api/passkeys/login/verify', {
		credential: {
			id: credential.id,
			rawId: toB64u(credential.rawId),
			type: credential.type,
			response: {
				clientDataJSON: toB64u(response.clientDataJSON),
				authenticatorData: toB64u(response.authenticatorData),
				signature: toB64u(response.signature),
				userHandle: toB64u(response.userHandle)
			},
			clientExtensionResults: credential.getClientExtensionResults(),
			authenticatorAttachment: credential.authenticatorAttachment ?? null
		}
	});
}

/** « MacBook », « iPhone »…: a first name for the passkey being created here. */
export function suggestedName(): string {
	const ua = navigator.userAgent;
	if (/iPhone/.test(ua)) return 'iPhone';
	if (/iPad/.test(ua)) return 'iPad';
	if (/Android/.test(ua)) return 'Téléphone Android';
	if (/Mac OS X|Macintosh/.test(ua)) return 'Mac';
	if (/Windows/.test(ua)) return 'PC Windows';
	return 'Cet appareil';
}
