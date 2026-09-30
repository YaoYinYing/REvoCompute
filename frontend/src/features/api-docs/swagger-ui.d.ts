declare module 'swagger-ui-dist/swagger-ui-es-bundle.js' {
  interface SwaggerUIConfig {
    url: string;
    domNode: HTMLElement;
    deepLinking?: boolean;
    persistAuthorization?: boolean;
    validatorUrl?: string | null;
  }
  export default function SwaggerUI(config: SwaggerUIConfig): unknown;
}
