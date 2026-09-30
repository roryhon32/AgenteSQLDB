/**
 * auth-transition.js — Motor de Transição de Autenticação Cinematográfica com GSAP.
 * 
 * Implementa a transição contínua e bidirecional (Login ↔ Home/Dashboard)
 * com foco no container azul e nas linhas curvas decorativas (sem morphing em círculo):
 * 
 *  1. Fluxo de LOGIN:
 *     - Saída: As linhas curvas saem deslizando para a DIREITA (translateX(120%) + fade out rápido).
 *     - Enquanto isso, o container azul desliza suavemente para a ESQUERDA enquanto sua largura (width)
 *       encolhe de forma contínua de 50% até 260px (duration: 0.7s, ease: cubic-bezier(0.16, 1, 0.3, 1)).
 *     - Entrada: Ao se acomodar no novo tamanho (260px), as linhas entram surgindo pela ESQUERDA
 *       (translateX(-120%) ➔ translateX(0) + fade in), cobrindo 100% da nova largura da base azul.
 * 
 *  2. Fluxo de LOGOUT (Inverso Exato):
 *     - Saída: As linhas da sidebar saem deslizando para a ESQUERDA (translateX(-120%) + fade out rápido).
 *     - O container azul desliza para a DIREITA enquanto sua largura expande de 260px de volta para 50%
 *       (duration: 0.7s, ease: cubic-bezier(0.16, 1, 0.3, 1)).
 *     - Entrada: As linhas retornam surgindo pela DIREITA (translateX(120%) ➔ translateX(0) + fade in),
 *       acomodando-se na base do layout original de login.
 * 
 * Requisitos:
 *  - Sem qualquer morphing ou transformação em círculo/spinner.
 *  - Persistência do nó do container azul no DOM sem saltos ou desmontagens.
 *  - 60fps constantes sem layout thrashing.
 *  - Acessibilidade: prefers-reduced-motion com fallback suave de 150ms.
 */

(function (global, factory) {
  if (typeof exports === 'object' && typeof module !== 'undefined') {
    module.exports = factory();
  } else if (typeof define === 'function' && define.amd) {
    define(factory);
  } else {
    global.AuthTransition = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // =========================================================================
  // 1. CONFIGURAÇÕES E CONSTANTES DA TIMELINE
  // =========================================================================
  const AUTH_CONFIG = {
    DURATIONS: {
      PANEL: 0.7,         // Deslocamento e redimensionamento do painel azul (0.7s conforme pedido)
      LINES_OUT: 0.32,    // Saída rápida das linhas curvas (fade out rápido)
      LINES_IN: 0.55,     // Entrada suave das linhas curvas (fade in)
      CONTENT: 0.32,      // Textos de branding e formulário
      FORM: 0.28,         // Formulário de credenciais
      REDUCED_MOTION: 0.15// Fallback de acessibilidade (150ms)
    },
    EASINGS: {
      PANEL: "cubic-bezier(0.16, 1, 0.3, 1)", // Curva de desaceleração suave calibrada
      LINES_OUT: "power2.in",                 // Aceleração rápida na saída
      LINES_IN: "cubic-bezier(0.16, 1, 0.3, 1)", // Entrada suave desacelerando
      EXIT: "power2.in",
      ENTRANCE: "power2.out"
    },
    OFFSETS: {
      PANEL_SIDEBAR_WIDTH: "260px",
      PANEL_LOGIN_WIDTH: "50%",
      PANEL_MOBILE_LOGIN_WIDTH: "100%",
      CONTENT_X: -40,
      FORM_Y: -15,
      ITEMS_X: -20,
      APP_Y: 20
    }
  };

  function getGSAP() {
    return typeof window !== 'undefined' ? (window.gsap || (typeof gsap !== 'undefined' ? gsap : null)) : null;
  }

  function prefersReducedMotion() {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  // =========================================================================
  // 2. MÁQUINA DE ESTADOS EXPLÍCITA (State Management)
  // =========================================================================
  const AuthState = {
    isLoggedIn: false,
    isLoading: false,
    direction: 'idle' // 'idle' | 'login' | 'logout'
  };

  function getAuthState() {
    return { ...AuthState };
  }

  function setAuthState(partialState) {
    Object.assign(AuthState, partialState);
    if (typeof window !== 'undefined' && window.dispatchEvent) {
      window.dispatchEvent(new CustomEvent('auth-state-changed', { detail: { ...AuthState } }));
    }
  }

  // =========================================================================
  // 3. RESOLUÇÃO DE ELEMENTOS DOM
  // =========================================================================
  function resolveElements(customElements = {}) {
    const doc = typeof document !== 'undefined' ? document : null;
    if (!doc) return {};

    const bluePanel = customElements.bluePanel || doc.getElementById("bluePanel");
    const loginArches = customElements.loginArches || doc.getElementById("loginArches") || doc.querySelector(".login-arches-bg");
    const sidebarArches = customElements.sidebarArches || doc.getElementById("sidebarArches") || doc.querySelector(".sidebar-arches-bg");

    return {
      bluePanel,
      loginArches,
      sidebarArches,
      loginLeftContent: customElements.loginLeftContent || doc.getElementById("loginLeftContent"),
      sidebarContent: customElements.sidebarContent || doc.getElementById("sidebarContent"),
      loginRightView: customElements.loginRightView || doc.getElementById("loginRightView"),
      loadingView: customElements.loadingView || doc.getElementById("loadingView"),
      authViewWrapper: customElements.authViewWrapper || doc.getElementById("authViewWrapper"),
      sidebarItems: customElements.sidebarItems || ".sidebar-logo, .menu-item, .sidebar-lgpd-card",
      chatElements: customElements.chatElements || ".chat-top-header, .welcome-screen-container, .chat-bottom-bar"
    };
  }

  // =========================================================================
  // 4. CRIADOR CENTRAL DA TRANSIÇÃO (createAuthTransition)
  // =========================================================================

  /**
   * Executa a transição direcional bidirecional do container azul e das linhas curvas.
   * 
   * @param {Object} params
   * @param {"in"|"out"} [params.direction="in"] - "in" (Login) | "out" (Logout)
   * @param {Object} [params.elements] - Overrides opcionais de referências DOM
   * @param {Function} [params.onStart] - Callback disparado no início
   * @param {Function} [params.onComplete] - Callback disparado após conclusão completa
   * @param {Function} [params.onUpdate] - Callback executado a cada frame
   * @param {boolean} [params.simulateReducedMotion=false]
   * @returns {gsap.core.Timeline|null}
   */
  function createAuthTransition(params = {}) {
    const gsapInstance = getGSAP();
    if (!gsapInstance) {
      console.error("[AuthTransition] GSAP não foi encontrado no ambiente.");
      if (params.onComplete) params.onComplete();
      return null;
    }

    const {
      direction = "in",
      elements = {},
      onStart = null,
      onComplete = null,
      onUpdate = null,
      simulateReducedMotion = false
    } = params;

    const isLogin = direction === "in";
    const isLogout = direction === "out";
    const el = resolveElements(elements);

    const isMobile = typeof window !== 'undefined' && window.innerWidth < 768;
    const loginPanelWidth = isMobile ? AUTH_CONFIG.OFFSETS.PANEL_MOBILE_LOGIN_WIDTH : AUTH_CONFIG.OFFSETS.PANEL_LOGIN_WIDTH;
    const sidebarPanelWidth = AUTH_CONFIG.OFFSETS.PANEL_SIDEBAR_WIDTH;

    // -----------------------------------------------------------------------
    // FALLBACK DE ACESSIBILIDADE (prefers-reduced-motion)
    // -----------------------------------------------------------------------
    if (prefersReducedMotion() || simulateReducedMotion) {
      const fallbackTl = gsapInstance.timeline({
        onStart: () => {
          setAuthState({ isLoading: true, isLoggedIn: !isLogin, direction });
          if (onStart) onStart();
        },
        onComplete: () => {
          if (isLogin) {
            if (typeof document !== 'undefined') {
              document.body.classList.add("is-authenticated");
              if (el.bluePanel) {
                el.bluePanel.classList.add("sidebar-mode");
                if (isMobile) el.bluePanel.style.removeProperty("width");
                else el.bluePanel.style.width = sidebarPanelWidth;
              }
            }
            if (el.loginRightView) el.loginRightView.style.display = "none";
            if (el.loginLeftContent) el.loginLeftContent.style.display = "none";
            if (el.sidebarContent) el.sidebarContent.style.display = "flex";
            if (el.authViewWrapper) {
              el.authViewWrapper.style.display = "flex";
              el.authViewWrapper.style.opacity = "1";
            }
            if (el.loginArches) el.loginArches.style.display = "none";
            if (el.sidebarArches) el.sidebarArches.style.display = "block";
            setAuthState({ isLoading: false, isLoggedIn: true, direction: 'idle' });
          } else {
            if (typeof document !== 'undefined') {
              document.body.classList.remove("is-authenticated");
              if (el.bluePanel) {
                el.bluePanel.classList.remove("sidebar-mode", "mobile-open");
                if (isMobile) el.bluePanel.style.removeProperty("width");
                else el.bluePanel.style.width = loginPanelWidth;
              }
            }
            if (el.authViewWrapper) el.authViewWrapper.style.display = "none";
            if (el.sidebarContent) el.sidebarContent.style.display = "none";
            if (el.loginLeftContent) {
              el.loginLeftContent.style.display = "flex";
              el.loginLeftContent.style.opacity = "1";
            }
            if (el.loginRightView) {
              el.loginRightView.style.display = "flex";
              el.loginRightView.style.opacity = "1";
            }
            if (el.sidebarArches) el.sidebarArches.style.display = "none";
            if (el.loginArches) el.loginArches.style.display = "block";
            setAuthState({ isLoading: false, isLoggedIn: false, direction: 'idle' });
          }
          if (onComplete) onComplete();
        }
      });

      if (isLogin) {
        if (el.loginRightView) fallbackTl.to(el.loginRightView, { opacity: 0, duration: AUTH_CONFIG.DURATIONS.REDUCED_MOTION });
        if (el.loginLeftContent) fallbackTl.to(el.loginLeftContent, { opacity: 0, duration: AUTH_CONFIG.DURATIONS.REDUCED_MOTION }, "<");
        if (el.authViewWrapper) {
          fallbackTl.set(el.authViewWrapper, { display: "flex", opacity: 0 });
          fallbackTl.to(el.authViewWrapper, { opacity: 1, duration: AUTH_CONFIG.DURATIONS.REDUCED_MOTION });
        }
      } else {
        if (el.authViewWrapper) fallbackTl.to(el.authViewWrapper, { opacity: 0, duration: AUTH_CONFIG.DURATIONS.REDUCED_MOTION });
        if (el.loginRightView) {
          fallbackTl.set(el.loginRightView, { display: "flex", opacity: 0 });
          fallbackTl.to(el.loginRightView, { opacity: 1, duration: AUTH_CONFIG.DURATIONS.REDUCED_MOTION });
        }
      }

      return fallbackTl;
    }

    // -----------------------------------------------------------------------
    // TIMELINE MASTER GSAP (Transição Contínua a 60fps)
    // -----------------------------------------------------------------------
    const tl = gsapInstance.timeline({
      onStart: () => {
        setAuthState({ isLoading: true, isLoggedIn: !isLogin, direction });
        if (onStart) onStart();
      },
      onUpdate: () => {
        if (onUpdate) onUpdate();
      },
      onComplete: () => {
        if (isLogin) {
          if (typeof document !== 'undefined') {
            document.body.classList.add("is-authenticated");
            if (el.bluePanel) el.bluePanel.classList.add("sidebar-mode");
          }
          setAuthState({ isLoading: false, isLoggedIn: true, direction: 'idle' });
        } else {
          if (typeof document !== 'undefined') {
            document.body.classList.remove("is-authenticated");
            if (el.bluePanel) el.bluePanel.classList.remove("sidebar-mode", "mobile-open");
          }
          setAuthState({ isLoading: false, isLoggedIn: false, direction: 'idle' });
        }
        if (onComplete) onComplete();
      }
    });

    const panelEl = el.bluePanel;

    if (isLogin) {
      // =====================================================================
      // FLUXO DE LOGIN:
      // 1. Saída: Linhas curvas deslizam para a DIREITA (translateX(120%) + fade out)
      // 2. Container azul desliza para a ESQUERDA e encolhe sua largura até 260px (duration: 0.7s)
      // 3. Entrada: Linhas surgem pela ESQUERDA (translateX(-120%) ➔ 0 + fade in)
      // =====================================================================

      // 1. Saída das linhas para a DIREITA
      if (el.loginArches) {
        tl.to(el.loginArches, {
          xPercent: 120, // ➔ DIREITA
          opacity: 0,
          duration: AUTH_CONFIG.DURATIONS.LINES_OUT,
          ease: AUTH_CONFIG.EASINGS.LINES_OUT,
          onComplete: () => {
            el.loginArches.style.display = "none";
          }
        }, 0);
      }

      // Saída do formulário de login e textos de boas-vindas
      if (el.loginRightView) {
        tl.to(el.loginRightView, {
          opacity: 0,
          y: AUTH_CONFIG.OFFSETS.FORM_Y,
          duration: AUTH_CONFIG.DURATIONS.FORM,
          ease: AUTH_CONFIG.EASINGS.EXIT,
          onComplete: () => {
            el.loginRightView.style.display = "none";
          }
        }, 0);
      }

      if (el.loginLeftContent) {
        tl.to(el.loginLeftContent, {
          opacity: 0,
          x: AUTH_CONFIG.OFFSETS.CONTENT_X,
          duration: AUTH_CONFIG.DURATIONS.CONTENT,
          ease: AUTH_CONFIG.EASINGS.EXIT,
          onComplete: () => {
            el.loginLeftContent.style.display = "none";
          }
        }, 0);
      }

      // 2. Container azul desliza para a ESQUERDA e encolhe sua largura de forma contínua até 260px
      if (panelEl) {
        tl.to(panelEl, {
          width: isMobile ? "100%" : sidebarPanelWidth,
          duration: AUTH_CONFIG.DURATIONS.PANEL, // 0.7s
          ease: AUTH_CONFIG.EASINGS.PANEL,       // cubic-bezier(0.16, 1, 0.3, 1)
          onStart: () => {
            if (el.sidebarContent) {
              el.sidebarContent.style.display = "flex";
              el.sidebarContent.style.opacity = "0";
            }
          }
        }, 0.04);
      }

      // 3. Entrada das linhas surgindo pela ESQUERDA na base da sidebar
      if (el.sidebarArches) {
        tl.fromTo(el.sidebarArches, {
          xPercent: -120, // ➔ SURGINDO PELA ESQUERDA
          opacity: 0,
          display: "block"
        }, {
          xPercent: 0,
          opacity: 1,
          duration: AUTH_CONFIG.DURATIONS.LINES_IN,
          ease: AUTH_CONFIG.EASINGS.LINES_IN
        }, "-=0.45");
      }

      // Entrada dos elementos da Sidebar (logo, itens de menu, LGPD)
      if (el.sidebarContent) {
        tl.to(el.sidebarContent, { opacity: 1, duration: 0.3 }, "-=0.35");
      }

      tl.fromTo(el.sidebarItems, {
        x: AUTH_CONFIG.OFFSETS.ITEMS_X,
        opacity: 0
      }, {
        x: 0,
        opacity: 1,
        duration: 0.35,
        stagger: 0.05,
        ease: AUTH_CONFIG.EASINGS.ENTRANCE
      }, "-=0.3");

      // Revela a área autenticada do Dashboard/Home
      if (el.authViewWrapper) {
        tl.set(el.authViewWrapper, { display: "flex", opacity: 0 }, "-=0.25")
          .to(el.authViewWrapper, { opacity: 1, duration: 0.35 }, "-=0.2");
      }

      tl.fromTo(el.chatElements, {
        y: AUTH_CONFIG.OFFSETS.APP_Y,
        opacity: 0
      }, {
        y: 0,
        opacity: 1,
        duration: 0.45,
        stagger: 0.06,
        ease: AUTH_CONFIG.EASINGS.ENTRANCE
      }, "-=0.2");

    } else if (isLogout) {
      // =====================================================================
      // FLUXO DE LOGOUT (INVERSO EXATO):
      // 1. Saída: Linhas da sidebar deslizam para a ESQUERDA (translateX(-120%) + fade out)
      // 2. Container azul desliza para a DIREITA e expande sua largura até 50% (duration: 0.7s)
      // 3. Entrada: Linhas retornam surgindo pela DIREITA (translateX(120%) ➔ 0 + fade in)
      // =====================================================================

      // 1. Saída das linhas para a ESQUERDA
      if (el.sidebarArches) {
        tl.to(el.sidebarArches, {
          xPercent: -120, // ➔ ESQUERDA
          opacity: 0,
          duration: AUTH_CONFIG.DURATIONS.LINES_OUT,
          ease: AUTH_CONFIG.EASINGS.LINES_OUT,
          onComplete: () => {
            el.sidebarArches.style.display = "none";
          }
        }, 0);
      }

      // Saída dos elementos autenticados (Dashboard e itens da sidebar)
      if (el.authViewWrapper) {
        tl.to(el.authViewWrapper, {
          opacity: 0,
          duration: 0.25,
          onComplete: () => {
            el.authViewWrapper.style.display = "none";
          }
        }, 0);
      }

      tl.to(el.sidebarItems, {
        x: AUTH_CONFIG.OFFSETS.ITEMS_X,
        opacity: 0,
        duration: 0.25,
        stagger: { each: 0.04, from: "end" },
        ease: AUTH_CONFIG.EASINGS.EXIT
      }, 0);

      if (el.sidebarContent) {
        tl.to(el.sidebarContent, { opacity: 0, duration: 0.2 }, 0);
      }

      // 2. Container azul desliza para a DIREITA e expande sua largura de volta para 50%
      if (panelEl) {
        tl.to(panelEl, {
          width: loginPanelWidth,
          duration: AUTH_CONFIG.DURATIONS.PANEL, // 0.7s
          ease: AUTH_CONFIG.EASINGS.PANEL,       // cubic-bezier(0.16, 1, 0.3, 1)
          onStart: () => {
            if (el.sidebarContent) el.sidebarContent.style.display = "none";
            if (el.loginLeftContent) {
              el.loginLeftContent.style.display = "flex";
              el.loginLeftContent.style.opacity = "0";
            }
          }
        }, 0.04);
      }

      // 3. Entrada das linhas retornando surgindo pela DIREITA na base do login
      if (el.loginArches) {
        tl.fromTo(el.loginArches, {
          xPercent: 120, // ➔ SURGINDO PELA DIREITA
          opacity: 0,
          display: "block"
        }, {
          xPercent: 0,
          opacity: 1,
          duration: AUTH_CONFIG.DURATIONS.LINES_IN,
          ease: AUTH_CONFIG.EASINGS.LINES_IN
        }, "-=0.45");
      }

      // Entrada dos textos de boas-vindas e do formulário de login
      if (el.loginLeftContent) {
        tl.to(el.loginLeftContent, {
          opacity: 1,
          x: 0,
          duration: 0.35,
          ease: AUTH_CONFIG.EASINGS.ENTRANCE
        }, "-=0.35");
      }

      if (el.loginRightView) {
        tl.set(el.loginRightView, {
          display: "flex",
          opacity: 0,
          y: AUTH_CONFIG.OFFSETS.FORM_Y
        }, "-=0.3")
        .to(el.loginRightView, {
          opacity: 1,
          y: 0,
          duration: 0.35,
          ease: AUTH_CONFIG.EASINGS.ENTRANCE
        }, "-=0.25");
      }
    }

    return tl;
  }

  // =========================================================================
  // 5. FACADES CONVENIENTES
  // =========================================================================
  function animateLogin(options = {}) {
    return createAuthTransition({ ...options, direction: "in" });
  }

  function animateLogout(options = {}) {
    return createAuthTransition({ ...options, direction: "out" });
  }

  // =========================================================================
  // 6. SUPORTE A REACT (useAuthTransition Hook)
  // =========================================================================
  function createReactHooks(ReactInstance) {
    if (!ReactInstance || !ReactInstance.useRef || !ReactInstance.useEffect) {
      return {};
    }

    const { useRef, useEffect, useState, useCallback } = ReactInstance;

    function useAuthTransition() {
      const activeTimelineRef = useRef(null);
      const [state, setState] = useState(getAuthState());

      useEffect(() => {
        function handleStateChange(e) {
          setState(e.detail);
        }
        if (typeof window !== 'undefined') {
          window.addEventListener('auth-state-changed', handleStateChange);
        }
        return () => {
          if (activeTimelineRef.current) activeTimelineRef.current.kill();
          if (typeof window !== 'undefined') {
            window.removeEventListener('auth-state-changed', handleStateChange);
          }
        };
      }, []);

      const login = useCallback((options = {}) => {
        if (activeTimelineRef.current) activeTimelineRef.current.kill();
        activeTimelineRef.current = animateLogin(options);
        return activeTimelineRef.current;
      }, []);

      const logout = useCallback((options = {}) => {
        if (activeTimelineRef.current) activeTimelineRef.current.kill();
        activeTimelineRef.current = animateLogout(options);
        return activeTimelineRef.current;
      }, []);

      const kill = useCallback(() => {
        if (activeTimelineRef.current) {
          activeTimelineRef.current.kill();
          activeTimelineRef.current = null;
        }
      }, []);

      return {
        login,
        logout,
        kill,
        isLoggedIn: state.isLoggedIn,
        isLoading: state.isLoading,
        direction: state.direction
      };
    }

    return { useAuthTransition };
  }

  const reactHooks = typeof window !== 'undefined' && window.React
    ? createReactHooks(window.React)
    : {};

  return {
    AUTH_CONFIG,
    getAuthState,
    setAuthState,
    createAuthTransition,
    animateLogin,
    animateLogout,
    prefersReducedMotion,
    createReactHooks,
    ...reactHooks
  };
});
