/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  User, Mail, Lock, Eye, EyeOff, ArrowRight, CheckCircle,
  MapPin, Landmark, Shield, Heart,
} from 'lucide-react';
import { ScreenId } from '../types';
import { useAuth } from '../context/AuthContext';
import { ApiError } from '../api';
import BrandLogo from './BrandLogo';
import { AUTH_HERO_SRC } from '../lib/utils';

interface JoinHeritageProps {
  onNextScreen: (next: ScreenId) => void;
}

type AuthMode = 'login' | 'register';

export default function JoinHeritage({ onNextScreen }: JoinHeritageProps) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<AuthMode>('login');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [error, setError] = useState('');

  const isRegister = mode === 'register';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError('');

    try {
      if (!email || !password || (isRegister && !fullName)) return;

      const nextScreen = isRegister
        ? await register(fullName, email, password)
        : await login(email, password);

      setShowSuccess(true);
      setIsSubmitting(false);
      onNextScreen(nextScreen);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Is the backend running?');
      setIsSubmitting(false);
    }
  };

  const switchMode = (next: AuthMode) => {
    setMode(next);
    setError('');
  };

  return (
    <div className="relative min-h-screen flex flex-col overflow-hidden">
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat"
        style={{ backgroundImage: `url(${AUTH_HERO_SRC})` }}
      />
      <div className="absolute inset-0 bg-[#f5ebe0]/85 backdrop-blur-[2px]" />

      <div className="relative z-10 flex flex-col min-h-screen px-4 py-8 max-w-lg mx-auto w-full">
        <header className="mb-6 flex justify-center pt-2">
          <BrandLogo size="hero" showTagline />
        </header>

        <section className="flex-grow flex flex-col">
          <div className="bg-white/95 rounded-2xl shadow-xl border border-[#e8d5c4]/60 px-6 py-8 md:px-8">
            <div className="flex justify-center mb-4">
              <div className="w-12 h-12 rounded-full border-2 border-[#c4a484] flex items-center justify-center text-[#8c4a2f]">
                {isRegister ? <User size={22} strokeWidth={1.5} /> : <Lock size={22} strokeWidth={1.5} />}
              </div>
            </div>

            <h1 className="font-serif text-2xl md:text-3xl text-center text-[#3d2914] font-semibold mb-1">
              {isRegister ? 'Create Account' : 'Welcome Back'}
            </h1>
            <p className="text-center text-sm text-[#7a6355] font-sans mb-6">
              {isRegister
                ? 'Sign up as an explorer — apply later to become an artisan'
                : 'Sign in with your email and password'}
            </p>

            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-xs font-sans">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              {isRegister && (
                <div>
                  <label className="block font-sans text-sm font-medium text-[#5c4a3d] mb-1.5">Full Name</label>
                  <div className="relative">
                    <input
                      type="text"
                      placeholder="E.g., Arjun Varma"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      className="w-full rounded-lg border border-[#ddd0c0] bg-[#faf7f2] px-4 py-3 pr-10 text-[#3d2914] text-sm outline-none focus:border-[#a0522d] focus:ring-1 focus:ring-[#a0522d]/30"
                      required
                    />
                    <User size={18} className="absolute right-3 top-3.5 text-[#b8a090]" />
                  </div>
                </div>
              )}

              <div>
                <label className="block font-sans text-sm font-medium text-[#5c4a3d] mb-1.5">Email Address</label>
                <div className="relative">
                  <input
                    type="email"
                    placeholder="you@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-lg border border-[#ddd0c0] bg-[#faf7f2] px-4 py-3 pr-10 text-[#3d2914] text-sm outline-none focus:border-[#a0522d] focus:ring-1 focus:ring-[#a0522d]/30"
                    required
                  />
                  <Mail size={18} className="absolute right-3 top-3.5 text-[#b8a090]" />
                </div>
              </div>

              <div>
                <label className="block font-sans text-sm font-medium text-[#5c4a3d] mb-1.5">Password</label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-lg border border-[#ddd0c0] bg-[#faf7f2] px-4 py-3 pr-12 text-[#3d2914] text-sm outline-none focus:border-[#a0522d] focus:ring-1 focus:ring-[#a0522d]/30"
                    required
                    minLength={6}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-3 text-[#b8a090] hover:text-[#a0522d]"
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                {isRegister && (
                  <p className="mt-1.5 text-xs text-[#8a7568] flex items-center gap-1">
                    <CheckCircle size={12} className="text-emerald-600" />
                    Use at least 6 characters
                  </p>
                )}
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full mt-2 bg-[#a0522d] hover:bg-[#8c4425] text-white font-sans font-semibold text-sm tracking-wider uppercase py-3.5 rounded-lg shadow-md active:scale-[0.99] transition-all flex items-center justify-center gap-2 disabled:opacity-70"
              >
                {isSubmitting ? 'Please wait...' : isRegister ? 'Create Account' : 'Sign In'}
                <ArrowRight size={16} />
              </button>
            </form>

            <p className="text-center text-sm text-[#7a6355] mt-5">
              {isRegister ? (
                <>
                  Already have an account?{' '}
                  <button type="button" onClick={() => switchMode('login')} className="text-[#a0522d] font-bold">
                    Sign in
                  </button>
                </>
              ) : (
                <>
                  Don&apos;t have an account?{' '}
                  <button type="button" onClick={() => switchMode('register')} className="text-[#a0522d] font-bold">
                    Sign up
                  </button>
                </>
              )}
            </p>
          </div>
        </section>

        <footer className="mt-8 grid grid-cols-2 gap-6 px-2 pb-6">
          {isRegister ? (
            <>
              <Feature icon={<MapPin size={20} />} title="Discover Hidden Gems" text="Offbeat places and unique experiences." />
              <Feature icon={<Landmark size={20} />} title="Cultural Heritage" text="Explore India's rich history and traditions." />
            </>
          ) : (
            <>
              <Feature icon={<Shield size={20} />} title="Travel Safe & Smart" text="Curated tips for a safe and smooth journey." />
              <Feature icon={<Heart size={20} />} title="Support Local" text="Empower local communities and preserve heritage." />
            </>
          )}
        </footer>
      </div>

      <div
        className={`fixed inset-0 z-50 bg-[#f5ebe0]/95 backdrop-blur-sm flex items-center justify-center px-4 transition-all duration-500 ${
          showSuccess ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
      >
        <div className="text-center space-y-4">
          <div className="w-20 h-20 bg-[#a0522d]/15 rounded-full flex items-center justify-center mx-auto">
            <CheckCircle className="text-[#a0522d]" size={40} />
          </div>
          <h2 className="font-serif text-2xl text-[#3d2914]">Welcome</h2>
          <p className="font-sans text-[#7a6355] text-sm max-w-xs mx-auto">
            Your heritage journey begins.
          </p>
        </div>
      </div>
    </div>
  );
}

function Feature({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div className="flex gap-3 items-start">
      <div className="text-[#a0522d] shrink-0 mt-0.5">{icon}</div>
      <div>
        <p className="font-sans text-sm font-bold text-[#3d2914]">{title}</p>
        <p className="font-sans text-xs text-[#7a6355] leading-snug mt-0.5">{text}</p>
      </div>
    </div>
  );
}
