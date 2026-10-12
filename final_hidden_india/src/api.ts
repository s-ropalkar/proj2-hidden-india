/**
 * Hidden India Explorer — API client (proxied via Vite to Flask backend)
 */

import type { Applicant, Artifact, Artisan, Workshop, RegionValidation } from './types';
import { stateMapPosition } from './lib/utils';

const TOKEN_KEY = 'hi_token';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  role: 'user' | 'artisan' | 'admin';
  geographicFocus: string;
  interests: string[];
  avatar: string;
  quizCompleted: boolean;
  applicationStatus?: 'none' | 'pending' | 'approved' | 'rejected';
  applicationNotes?: string;
  preferredStates?: string[];
  favoriteCrafts?: string[];
  preferredRegions?: string[];
  workshopInterest?: string;
}

export interface QuizPayload {
  visitReason: string;
  interests: string[];
  crafts: string[];
  regions: string[];
  workshopInterest: string;
  budget: string;
}

export interface Recommendations {
  artisans: Artisan[];
  products: Artifact[];
  workshops: Workshop[];
  regions: Array<{ id: string; name: string; state: string; highlight_craft?: string }>;
}

export interface MapRegionPin {
  id: string;
  name: string;
  state: string;
  category: string;
  craft: string;
  info: string;
  image: string;
  count: number;
  lng: number;
  lat: number;
  x: string;
  y: string;
  artisan?: string;
  color?: string;
}

export interface NearbyArtisan {
  id: string;
  name: string;
  craft: string;
  state: string;
  category: string;
  distance: string;
  rating: number;
  snippet: string;
  avatar: string;
}

export interface AdminAnalytics {
  totalUsers: number;
  totalArtisans: number;
  totalProducts: number;
  totalWorkshops: number;
  pendingApplications: number;
  approvedApplications?: number;
  mostExploredState: string;
  mostExploredRegion?: string;
  mostLikedCategory?: string;
  mostSavedArtisan: string;
  mostRegisteredWorkshop: string;
  totalOrders: number;
  totalWorkshopRegistrations?: number;
  artisanClusters?: number;
  monthlyTrends?: Array<{ label: string; value: number; heightPct: number }>;
  approvedArtisans?: Array<{ id: string; name: string; state: string; category: string; crafts: string[] }>;
  insightCards?: string[];
}

function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }

  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...options, headers });
  } catch {
    throw new ApiError('Cannot reach server — run npm start from the project root', 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(data.error || data.message || `Request failed (${res.status})`, res.status);
  }
  return data as T;
}

function mapArtisan(doc: Record<string, unknown>): Artisan {
  return {
    id: String(doc.id),
    name: String(doc.name || ''),
    region: String(doc.region || ''),
    category: String(doc.category || ''),
    avatar: String(doc.avatar || ''),
    bio: String(doc.bio || ''),
    rating: typeof doc.rating === 'number' ? doc.rating : undefined,
    highlightImage: String(doc.highlight_image || doc.highlightImage || doc.avatar || ''),
    tag: (doc.tag as Artisan['tag']) || 'Next Gen',
  };
}

function mapProduct(doc: Record<string, unknown>): Artifact & {
  state?: string;
  description?: string;
  artisan?: string;
  material?: string;
  priceDisplay?: string;
} {
  const priceRaw = doc.price_display || doc.price || doc.price_num || '';
  const priceStr = String(priceRaw).replace(/[₹,]/g, '').trim();
  return {
    id: String(doc.id),
    name: String(doc.name || ''),
    price: priceStr || '0',
    category: (doc.category as Artifact['category']) || 'Decor',
    image: String(doc.image || ''),
    status: (doc.status as Artifact['status']) || 'In Stock',
    state: String(doc.state || ''),
    description: String(doc.description || ''),
    artisan: String(
      doc.artisan_name
      || (typeof doc.artisan === 'object' && doc.artisan
        ? (doc.artisan as Record<string, unknown>).name
        : doc.artisan)
      || ''
    ),
    material: String(doc.material || ''),
    priceDisplay: String(doc.price_display || `₹${priceStr}`),
  };
}

function mapWorkshop(doc: Record<string, unknown>): Workshop {
  const modeRaw = String(doc.mode || 'offline').toLowerCase();
  return {
    id: String(doc.id),
    title: String(doc.title || ''),
    instructor: String(doc.instructor || ''),
    instructorAvatar: String(doc.instructor_avatar || doc.instructorAvatar || ''),
    date: String(doc.date || ''),
    time: String(doc.time || ''),
    price: String(doc.price_display || doc.price || ''),
    category: (doc.category as Workshop['category']) || 'Hands-on',
    thumbnail: String(doc.thumbnail || ''),
    venue: String(doc.venue || ''),
    mode: modeRaw === 'online' ? 'online' : 'offline',
    state: String(doc.state || ''),
  };
}

function mapApplicant(doc: Record<string, unknown>): Applicant {
  return {
    id: String(doc.id),
    name: String(doc.name || ''),
    email: String(doc.email || ''),
    category: String(doc.category || ''),
    crafts: Array.isArray(doc.crafts) ? doc.crafts.map(String) : [],
    state: String(doc.state || ''),
    region: String(doc.region || ''),
    craftIcon: String(doc.craftIcon || doc.craft_icon || 'brush'),
    date: String(doc.date || ''),
    status: (doc.status as Applicant['status']) || 'pending',
    govtIdUrl: String(doc.govtIdUrl || doc.govt_id_url || ''),
    certUrl: String(doc.certUrl || doc.cert_url || ''),
    portfolio: Array.isArray(doc.portfolio) ? doc.portfolio.map(String) : [],
    regionValidation: doc.regionValidation as Applicant['regionValidation'],
  };
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function register(name: string, email: string, password: string) {
  const data = await request<{ token: string; user: AuthUser }>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ name, email, password }),
  });
  setToken(data.token);
  return data;
}

export async function login(email: string, password: string) {
  const data = await request<{ token: string; user: AuthUser }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  setToken(data.token);
  return data;
}

export async function getMe(): Promise<AuthUser> {
  const data = await request<{ user: AuthUser }>('/auth/me');
  return data.user;
}

export function logout() {
  setToken(null);
}

export function homeScreenForUser(user: AuthUser): string {
  if (user.role === 'admin') return 'supervisor-dashboard';
  if (user.role === 'artisan') return 'artisan-dashboard';
  if (user.applicationStatus === 'pending' || user.applicationStatus === 'rejected') {
    return 'artisan-application-status';
  }
  return user.quizCompleted ? 'personalized-dashboard' : 'artistic-echoes';
}

// ── User ──────────────────────────────────────────────────────────────────────

export async function saveQuiz(quiz: QuizPayload) {
  return request<{ success: boolean; profile: AuthUser }>('/users/me/quiz', {
    method: 'POST',
    body: JSON.stringify(quiz),
  });
}

export async function updateProfile(payload: Partial<{ name: string; geographicFocus: string; interests: string[] }>) {
  return request<AuthUser>('/users/me', { method: 'PATCH', body: JSON.stringify(payload) });
}

export async function getRecommendations(): Promise<Recommendations> {
  const data = await request<{
    artisans: Record<string, unknown>[];
    products: Record<string, unknown>[];
    workshops: Record<string, unknown>[];
    regions: Record<string, unknown>[];
  }>('/users/me/recommendations');
  return {
    artisans: (data.artisans || []).map(mapArtisan),
    products: (data.products || []).map(mapProduct),
    workshops: (data.workshops || []).map(mapWorkshop),
    regions: (data.regions || []).map((r) => ({
      id: String(r.id),
      name: String(r.name),
      state: String(r.state),
      highlight_craft: String(r.highlight_craft || ''),
    })),
  };
}

export async function getSavedItems() {
  const data = await request<Record<string, unknown>[]>('/users/me/saved');
  return data.map((item) => ({
    id: String(item.id),
    name: String(item.name || ''),
    craft: String(item.craft || item.category || ''),
    origin: String(item.state || item.region || ''),
    price: String(item.price_display || item.price || ''),
    img: String(item.image || item.avatar || ''),
    savedType: String(item.savedType || 'product'),
  }));
}

export async function saveItem(itemType: 'product' | 'artisan', itemId: string) {
  return request('/users/me/saved', {
    method: 'POST',
    body: JSON.stringify({ itemType, itemId }),
  });
}

export async function unsaveItem(itemType: string, itemId: string) {
  return request(`/users/me/saved/${itemType}/${itemId}`, { method: 'DELETE' });
}

export async function placeOrder(productId: string, quantity = 1, buyNow = true) {
  return request<{ orderId: string; status: string }>('/orders', {
    method: 'POST',
    body: JSON.stringify({ productId, quantity, buyNow }),
  });
}

export async function getMyOrders() {
  const data = await request<Array<Record<string, unknown>>>('/users/me/orders');
  return data.map((o) => {
    const product = o.product as Record<string, unknown> | null;
    return {
      id: String(o.id),
      status: String(o.status || 'Placed'),
      quantity: Number(o.quantity || 1),
      total: Number(o.total || 0),
      createdAt: String(o.createdAt || ''),
      product: product
        ? {
            id: String(product.id),
            name: String(product.name || ''),
            image: String(product.image || ''),
            price: String(product.price_display || product.price || ''),
            category: String(product.category || ''),
            state: String(product.state || ''),
          }
        : null,
    };
  });
}

export interface UserWorkshopBooking {
  id: string;
  workshopId: string;
  name: string;
  host: string;
  date: string;
  time: string;
  price: string;
  status: string;
  mode: 'online' | 'offline';
  venue: string;
}

export async function getMyWorkshops() {
  const data = await request<{
    upcoming: Record<string, unknown>[];
    attended: Record<string, unknown>[];
  }>('/users/me/workshops');
  const mapWs = (ws: Record<string, unknown>): UserWorkshopBooking => ({
    id: String(ws.id || ws.registrationId || ''),
    workshopId: String(ws.workshopId || ''),
    name: String(ws.name || ''),
    host: String(ws.host || ''),
    date: String(ws.date || ''),
    time: String(ws.time || ''),
    price: String(ws.price || ''),
    status: String(ws.status || ''),
    mode: String(ws.mode || 'offline').toLowerCase() === 'online' ? 'online' : 'offline',
    venue: String(ws.venue || ''),
  });
  return {
    upcoming: (data.upcoming || []).map(mapWs),
    attended: (data.attended || []).map(mapWs),
  };
}

// ── Discovery ─────────────────────────────────────────────────────────────────

export async function getProducts(params?: { category?: string; state?: string }) {
  const qs = new URLSearchParams();
  if (params?.category) qs.set('category', params.category);
  if (params?.state) qs.set('state', params.state);
  const data = await request<Record<string, unknown>[]>(`/products?${qs}`);
  return data.map(mapProduct);
}

export async function getWorkshops(params?: { category?: string; state?: string }) {
  const qs = new URLSearchParams();
  if (params?.category) qs.set('category', params.category);
  if (params?.state) qs.set('state', params.state);
  const suffix = qs.toString() ? `?${qs}` : '';
  const data = await request<Record<string, unknown>[]>(`/workshops${suffix}`);
  return data.map(mapWorkshop);
}

export async function getCatalogStates() {
  return request<{ states: string[]; craftsByState: Record<string, string[]> }>('/catalog/states');
}

export async function getCatalogCrafts() {
  const data = await request<{ crafts: string[] }>('/catalog/crafts');
  return data.crafts;
}

export async function validateApplicationCrafts(state: string, crafts: string[]) {
  return request<RegionValidation>('/catalog/validate-crafts', {
    method: 'POST',
    body: JSON.stringify({ state, crafts }),
  });
}

export async function getWorkshop(id: string) {
  const data = await request<Record<string, unknown>>(`/workshops/${id}`);
  return {
    ...mapWorkshop(data),
    seatsAvailable: Number(data.seatsAvailable ?? 0),
    seatsTotal: Number(data.seatsTotal ?? 20),
    seatsRegistered: Number(data.seatsRegistered ?? 0),
    isRegistered: Boolean(data.isRegistered),
  };
}

export async function registerWorkshop(workshopId: string, sessionId = 'session-1') {
  return request(`/workshops/${workshopId}/register`, {
    method: 'POST',
    body: JSON.stringify({ sessionId }),
  });
}

export async function getMapRegions(): Promise<MapRegionPin[]> {
  const data = await request<Array<Record<string, unknown>>>('/map/regions');
  return data.map((r) => {
    const lat = Number(r.lat) || 20;
    const lng = Number(r.lng) || 78;
    const pos = stateMapPosition(String(r.state || ''), lat, lng);
    return {
      id: String(r.id),
      name: String(r.name),
      state: String(r.state),
      category: String(r.category || r.craft || ''),
      craft: String(r.craft || r.category || ''),
      info: String(r.info || ''),
      image: String(r.image || ''),
      count: Number(r.count) || 0,
      artisan: String(r.artisan || ''),
      lng,
      lat,
      x: pos.x,
      y: pos.y,
      color: '#ac4425',
    };
  });
}

export async function getNearbyArtisans(lat: number, lng: number, km = 25) {
  const data = await request<Record<string, unknown>[]>(
    `/map/nearby?lat=${lat}&lng=${lng}&km=${km}&type=artisan`
  );
  return data.map(
    (a): NearbyArtisan => ({
      id: String(a.id),
      name: String(a.name || ''),
      craft: String(a.craft || a.category || ''),
      state: String(a.state || ''),
      category: String(a.category || ''),
      distance: String(a.distance || ''),
      rating: Number(a.rating) || 4.5,
      snippet: String(a.snippet || a.bio || '').slice(0, 120),
      avatar: String(a.avatar || ''),
    })
  );
}

export async function getRegion(state: string) {
  const data = await request<Record<string, unknown>>(`/regions/${encodeURIComponent(state)}`);
  return {
    products: (Array.isArray(data.products) ? data.products : []).map((p) => mapProduct(p as Record<string, unknown>)),
    workshops: (Array.isArray(data.workshops) ? data.workshops : []).map((w) => mapWorkshop(w as Record<string, unknown>)),
    artisans: (Array.isArray(data.artisans) ? data.artisans : []).map((a) => mapArtisan(a as Record<string, unknown>)),
    region: data.region as Record<string, unknown> | undefined,
  };
}

// ── Artisan application ───────────────────────────────────────────────────────

export async function submitArtisanApplication(form: FormData) {
  return request('/artisan/apply', { method: 'POST', body: form });
}

export async function getApplicationStatus() {
  return request<{
    status: string;
    category?: string;
    region?: string;
    date?: string;
    state?: string;
    curatorNotes?: string;
    reviewedAt?: string;
  }>('/artisan/application/status');
}

// ── Artisan dashboard ─────────────────────────────────────────────────────────

export async function getArtisanProfile() {
  const data = await request<Record<string, unknown>>('/artisan/profile');
  return {
    ...data,
    approvedCrafts: Array.isArray(data.approved_crafts)
      ? (data.approved_crafts as string[])
      : Array.isArray(data.approvedCrafts)
        ? (data.approvedCrafts as string[])
        : data.category
          ? String(data.category).split(',').map((s) => s.trim()).filter(Boolean)
          : [],
    state: String(data.state || ''),
    highlightImage: String(data.highlight_image || data.highlightImage || data.portfolio_image || ''),
    bio: String(data.bio || ''),
    name: String(data.name || ''),
  };
}

export async function updateArtisanProfile(payload: Record<string, unknown>) {
  return request('/artisan/profile', { method: 'PATCH', body: JSON.stringify(payload) });
}

export async function getArtisanProducts() {
  const data = await request<Record<string, unknown>[]>('/artisan/products');
  return data.map(mapProduct);
}

export async function createArtisanProduct(payload: Record<string, unknown>) {
  const data = await request<Record<string, unknown>>('/artisan/products', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return mapProduct(data);
}

export async function updateArtisanProduct(id: string, payload: Record<string, unknown>) {
  const data = await request<Record<string, unknown>>(`/artisan/products/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return mapProduct(data);
}

export async function deleteArtisanProduct(id: string) {
  return request(`/artisan/products/${id}`, { method: 'DELETE' });
}

export async function getArtisanWorkshops() {
  const data = await request<Record<string, unknown>[]>('/artisan/workshops');
  return data.map(mapWorkshop);
}

export async function createArtisanWorkshop(payload: Record<string, unknown>) {
  const data = await request<Record<string, unknown>>('/artisan/workshops', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return mapWorkshop(data);
}

export async function updateArtisanWorkshop(id: string, payload: Record<string, unknown>) {
  return request(`/artisan/workshops/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
}

export async function deleteArtisanWorkshop(id: string) {
  return request(`/artisan/workshops/${id}`, { method: 'DELETE' });
}

export async function getArtisanAnalytics() {
  return request<{
    workshopRegistrations: number;
    productsPurchased: number;
    productsViewed: number;
  }>('/artisan/analytics');
}

export async function getArtisanRegistrations() {
  return request<
    Array<{ id: string; student: string; course: string; date: string; time: string; seats: number; status: string }>
  >('/artisan/registrations');
}

export async function updateArtisanRegistration(id: string, status: string) {
  return request<{ success: boolean; status: string }>(`/artisan/registrations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

export async function uploadArtisanPortfolio(file: File) {
  const form = new FormData();
  form.append('portfolio', file);
  const token = localStorage.getItem(TOKEN_KEY);
  const res = await fetch('/api/artisan/profile/portfolio', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  const data = await res.json();
  if (!res.ok) throw new ApiError(data.error || 'Upload failed', res.status);
  return data as { url: string; highlightImage: string };
}

export interface AppNotification {
  id: string;
  type: string;
  title: string;
  message: string;
  read: boolean;
  createdAt: string;
  meta: Record<string, unknown>;
}

export async function getNotifications() {
  return request<{ unread: number; items: AppNotification[] }>('/users/me/notifications');
}

export async function markNotificationsRead() {
  return request('/users/me/notifications/read', { method: 'PATCH' });
}

export async function trackProductView(productId: string) {
  return request(`/products/${productId}/view`, { method: 'POST' });
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export async function getAdminAnalytics(): Promise<AdminAnalytics> {
  return request<AdminAnalytics>('/admin/analytics');
}

export async function getAdminApplications(status = 'pending') {
  const data = await request<Record<string, unknown>[]>(`/admin/applications?status=${status}`);
  return data.map(mapApplicant);
}

export async function reviewApplication(appId: string, status: 'approved' | 'rejected', curatorNotes?: string) {
  return request(`/admin/applications/${appId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status, curatorNotes }),
  });
}

export async function getAdminUsers() {
  return request<
    Array<{ id: string; name: string; email: string; interests: string; status: string; joined: string; role: string }>
  >('/admin/users');
}

export async function setUserStatus(userId: string, status: 'Active' | 'Blocked') {
  return request(`/admin/users/${userId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

export async function getAdminArtisans() {
  return request<
    Array<{ id: string; name: string; region: string; category: string; status: string; sales: string }>
  >('/admin/artisans');
}

export async function setArtisanStatus(artisanId: string, status: 'Active' | 'Suspended') {
  return request(`/admin/artisans/${artisanId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}
